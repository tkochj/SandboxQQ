import os
import sys
import json
import atexit
import socket
import logging
import threading
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_firewall_rules_registry = set()
_mw_lock = threading.Lock()

def _cleanup_orphaned_firewall_rules():
    with _mw_lock:
        rules = list(_firewall_rules_registry)
        if not rules:
            return
        try:
            import win32com.client
            fw_policy = win32com.client.Dispatch("HNetCfg.FwPolicy2")
            for name in rules:
                try:
                    fw_policy.Rules.Remove(name)
                except Exception:
                    pass
        except Exception:
            pass

atexit.register(_cleanup_orphaned_firewall_rules)


class NetworkSandbox:
    def __init__(self, sandbox_root: str, allowed_hosts: Optional[List[str]] = None):
        self.sandbox_root = Path(sandbox_root).resolve()
        self.allowed_hosts = allowed_hosts or []
        self._original_socket_connect = None
        self._active = False
        self._stats = {"blocked_count": 0, "allowed_count": 0}
        self._firewall_rules = []

    def activate(self):
        if self._active:
            return
        self._original_socket_connect = socket.socket.connect
        socket.socket.connect = self._make_sandboxed_connect()
        self._active = True
        self._setup_firewall_rules()
        logger.info(
            f"Network sandbox activated, allowed hosts: {self.allowed_hosts}"
        )

    def deactivate(self):
        if not self._active:
            return
        if self._original_socket_connect:
            socket.socket.connect = self._original_socket_connect
        self._cleanup_firewall_rules()
        self._active = False
        logger.info("Network sandbox deactivated")

    def _setup_firewall_rules(self):
        try:
            import win32com.client

            fw_policy = win32com.client.Dispatch("HNetCfg.FwPolicy2")
            rules = fw_policy.Rules

            process_path = sys.executable.lower()

            block_rule_name = f"Sandbox_Block_{id(self)}"
            try:
                existing = fw_policy.Rules.Item(block_rule_name)
                fw_policy.Rules.Remove(block_rule_name)
            except Exception:
                pass

            new_rule = win32com.client.Dispatch("HNetCfg.FWRule")
            new_rule.Name = block_rule_name
            new_rule.Description = "Sandbox network isolation (block all)"
            new_rule.ApplicationName = process_path
            new_rule.Action = 0
            new_rule.Direction = 1
            new_rule.Enabled = True
            new_rule.Profiles = 0x7FFFFFFF
            try:
                fw_policy.Rules.Add(new_rule)
                self._firewall_rules.append(block_rule_name)
                with _mw_lock:
                    _firewall_rules_registry.add(block_rule_name)
                logger.info(f"Added firewall block rule for {process_path}")
            except Exception as e:
                logger.warning(f"Failed to add firewall rule: {e}")

            if self.allowed_hosts:
                for host in self.allowed_hosts:
                    try:
                        allow_rule_name = f"Sandbox_Allow_{host}_{id(self)}"
                        try:
                            existing = fw_policy.Rules.Item(allow_rule_name)
                            fw_policy.Rules.Remove(allow_rule_name)
                        except Exception:
                            pass

                        allow_rule = win32com.client.Dispatch("HNetCfg.FWRule")
                        allow_rule.Name = allow_rule_name
                        allow_rule.Description = f"Sandbox allow {host}"
                        allow_rule.ApplicationName = process_path
                        allow_rule.Action = 1
                        allow_rule.Direction = 1
                        allow_rule.Enabled = True
                        allow_rule.Profiles = 0x7FFFFFFF

                        hostname = urlparse(host).hostname if "://" in host else host
                        if hostname:
                            resolved = self._resolve_host(hostname)
                            if not resolved:
                                logger.warning(
                                    f"Skipping allow rule for {host}: DNS resolution failed"
                                )
                                continue
                            allow_rule.RemoteAddresses = resolved
                            try:
                                fw_policy.Rules.Add(allow_rule)
                                self._firewall_rules.append(allow_rule_name)
                                with _mw_lock:
                                    _firewall_rules_registry.add(allow_rule_name)
                                logger.info(
                                    f"Added allow rule for {host} -> {hostname}"
                                )
                            except Exception as e:
                                logger.warning(
                                    f"Failed to add allow rule for {host}: {e}"
                                )
                    except Exception:
                        pass

        except ImportError:
            logger.info("pywin32 firewall API not available, using socket-level isolation only")
        except Exception as e:
            logger.warning(f"Firewall setup failed, using socket isolation: {e}")

    def _resolve_host(self, hostname: str) -> str:
        try:
            ips = set()
            bare = hostname
            if hostname.startswith("wss://") or hostname.startswith("ws://"):
                bare = hostname.split("://")[1].split(":")[0].split("/")[0]
            try:
                for info in socket.getaddrinfo(bare, 443):
                    ips.add(info[4][0])
            except Exception:
                pass
            if ips:
                return ",".join(f"{ip}/32" for ip in ips)
        except Exception:
            pass
        logger.warning(f"DNS resolution failed for {hostname}, skipping allow rule")
        return ""

    def _cleanup_firewall_rules(self):
        try:
            import win32com.client
            fw_policy = win32com.client.Dispatch("HNetCfg.FwPolicy2")
            for rule_name in self._firewall_rules:
                try:
                    fw_policy.Rules.Remove(rule_name)
                    with _mw_lock:
                        _firewall_rules_registry.discard(rule_name)
                    logger.info(f"Removed firewall rule: {rule_name}")
                except Exception:
                    pass
        except Exception:
            pass
        self._firewall_rules.clear()

    def _make_sandboxed_connect(self):
        original = self._original_socket_connect
        is_allowed = self._is_host_allowed
        stats = self._stats
        stats_lock = threading.Lock()
        def sandboxed_connect(sock, address):
            if isinstance(address, tuple):
                host, port = address
            elif isinstance(address, str):
                host = address.split(":")[0]
                port = int(address.split(":")[1]) if ":" in address else 0
            else:
                return original(sock, address)

            if is_allowed(host, port):
                with stats_lock:
                    stats["allowed_count"] += 1
                return original(sock, address)
            else:
                with stats_lock:
                    stats["blocked_count"] += 1
                logger.warning(f"Blocked network connection to {host}:{port}")
                raise BlockedHostError(f"Network access to {host}:{port} blocked by sandbox")
        return sandboxed_connect

    def _is_host_allowed(self, host: str, port: int) -> bool:
        if not self.allowed_hosts:
            return False

        for allowed in self.allowed_hosts:
            parsed = urlparse(allowed) if "://" in allowed else urlparse(f"//{allowed}")
            allowed_host = parsed.hostname or allowed
            allowed_port = parsed.port

            if allowed_host == host:
                if allowed_port is None or allowed_port == port:
                    return True

            try:
                host_ip = socket.gethostbyname(host)
                allowed_ip = socket.gethostbyname(allowed_host)
                if host_ip == allowed_ip:
                    return True
            except Exception:
                if host == allowed_host:
                    return True

        known_safe = [
            ("localhost", 0),
            ("127.0.0.1", 0),
            ("::1", 0),
        ]
        for safe_host, safe_port in known_safe:
            if host == safe_host and (safe_port == 0 or safe_port == port):
                return True

        return False

    def add_allowed_host(self, host: str):
        if host not in self.allowed_hosts:
            self.allowed_hosts.append(host)
            logger.info(f"Added allowed host: {host}")

    def remove_allowed_host(self, host: str):
        if host in self.allowed_hosts:
            self.allowed_hosts.remove(host)

    def get_stats(self) -> dict:
        return dict(self._stats)


class BlockedHostError(Exception):
    pass
