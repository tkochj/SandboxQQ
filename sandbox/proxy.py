"""
本地正向代理，仅用于沙盒子进程的网络隔离。
子进程通过 HTTP_PROXY/HTTPS_PROXY 环境变量将流量导向此代理。
代理按域名白名单放行或拒绝。
"""
import asyncio
import logging
import socket
from typing import Optional

logger = logging.getLogger(__name__)

PROXY_PORT_RANGE = (23100, 23199)


class ProxySandbox:
    def __init__(self, allowed_hosts: Optional[list] = None):
        raw = allowed_hosts or []
        normalized = []
        for h in raw:
            h = h.lower().strip()
            from urllib.parse import urlparse
            if "://" in h:
                h = urlparse(h).hostname or h
            normalized.append(h)
        self.allowed_hosts = normalized
        self._server: Optional[asyncio.AbstractServer] = None
        self._port: int = 0

    @property
    def proxy_url(self) -> str:
        return f"http://127.0.0.1:{self._port}" if self._port else ""

    def is_allowed(self, host: str) -> bool:
        if not self.allowed_hosts:
            return True
        host = host.lower()
        for allowed in self.allowed_hosts:
            a = allowed.lower().strip()
            if a.startswith("*."):
                suffix = a[1:]
                if host.endswith(suffix) or host == a[2:]:
                    return True
            elif host == a:
                return True
        return False

    async def start(self):
        for port in range(PROXY_PORT_RANGE[0], PROXY_PORT_RANGE[1] + 1):
            try:
                self._server = await asyncio.start_server(
                    self._handle_client, host="127.0.0.1", port=port
                )
                self._port = port
                logger.info(f"Proxy running on 127.0.0.1:{port}")
                asyncio.create_task(self._server.serve_forever())
                return
            except OSError:
                continue
        raise RuntimeError("No available port for proxy")

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            self._port = 0
            logger.info("Proxy stopped")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        loop = asyncio.get_running_loop()
        try:
            data = await asyncio.wait_for(reader.readline(), timeout=10)
            if not data:
                return
            request_line = data.decode("utf-8", errors="replace").strip()
            parts = request_line.split()
            if len(parts) < 3:
                return
            method, target = parts[0], parts[1]

            if method.upper() == "CONNECT":
                host_port = target
                host = host_port.rsplit(":", 1)[0] if ":" in host_port else host_port
                remote_port = int(host_port.rsplit(":", 1)[1]) if ":" in host_port else 443
                if not self.is_allowed(host):
                    writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                    await writer.drain()
                    logger.warning(f"Proxy BLOCKED CONNECT: {host}")
                    return
                while True:
                    line = await asyncio.wait_for(reader.readline(), timeout=10)
                    if line in (b"\r\n", b"\n", b""):
                        break
                try:
                    # Use run_in_executor for socket connect (Windows child thread compat)
                    remote_sock = await loop.run_in_executor(
                        None, self._blocking_connect, host, remote_port
                    )
                    remote_reader, remote_writer = await asyncio.open_connection(
                        sock=remote_sock
                    )
                except Exception as e:
                    writer.write(f"HTTP/1.1 502 Bad Gateway\r\n\r\n".encode())
                    await writer.drain()
                    logger.warning(f"Proxy CONNECT failed to {host}: {e}")
                    return
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
                await asyncio.gather(
                    self._relay(reader, remote_writer),
                    self._relay(remote_reader, writer),
                    return_exceptions=True,
                )
                remote_writer.close()
            else:
                from urllib.parse import urlparse
                parsed = urlparse(target)
                host = parsed.hostname or ""
                remote_port = parsed.port or 80
                if not host:
                    while True:
                        line = (await asyncio.wait_for(reader.readline(), timeout=10)).decode("utf-8", errors="replace").strip()
                        if line.lower().startswith("host:"):
                            host = line[5:].strip().split(":")[0]
                            if ":" in line[5:].strip():
                                remote_port = int(line[5:].strip().split(":")[1])
                            break
                        if line == "":
                            break
                if not self.is_allowed(host):
                    writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                    await writer.drain()
                    logger.warning(f"Proxy BLOCKED HTTP: {host}")
                    return
                try:
                    remote_sock = await loop.run_in_executor(
                        None, self._blocking_connect, host, remote_port
                    )
                    remote_reader, remote_writer = await asyncio.open_connection(
                        sock=remote_sock
                    )
                except Exception as e:
                    writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                    await writer.drain()
                    return
                remote_writer.write(data)
                await remote_writer.drain()
                await asyncio.gather(
                    self._relay(reader, remote_writer),
                    self._relay(remote_reader, writer),
                    return_exceptions=True,
                )
                remote_writer.close()
        except Exception as e:
            logger.debug(f"Proxy handler error: {e}")
        finally:
            try:
                writer.close()
            except Exception:
                pass

    @staticmethod
    def _blocking_connect(host: str, port: int) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((socket.getaddrinfo(host, port)[0][4][0], port))
        sock.settimeout(300)
        return sock

    async def _relay(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            while True:
                data = await asyncio.wait_for(reader.read(65536), timeout=300)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (asyncio.TimeoutError, ConnectionError, OSError):
            pass
