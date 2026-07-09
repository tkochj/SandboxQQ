import os
import sys
import json
import time
import logging
import threading
import psutil
from pathlib import Path
from typing import Optional, Callable

from utils.win32_utils import JobObjectManager, TokenManager, HAS_PYWIN32
from sandbox.network import NetworkSandbox
from sandbox.process import ProcessSandbox
from sandbox.proxy import ProxySandbox

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    from sandbox.filesystem import FileSystemSandbox
else:
    # Linux/macOS 不使用文件系统沙盒（AppContainer 不可用）
    class FileSystemSandbox:
        def __init__(self, *a, **kw): self._stats = {"blocked_count": 0, "redirected_count": 0}
        def activate(self): pass
        def deactivate(self): pass
        def resolve_path(self, p): return p
        def get_stats(self): return {}
        def list_sandbox_files(self, r=True): return []
        def add_allowed_write_dir(self, p): pass


class SandboxConfig:
    def __init__(self):
        self.root_dir: str = ""
        self.enable_file_isolation: bool = True
        self.enable_network_isolation: bool = True
        self.enable_process_isolation: bool = True
        self.active_process_limit: int = 10
        self.memory_limit_mb: int = 512
        self.cpu_rate_limit: int = 0
        self.allowed_hosts: list = []
        sysroot = os.environ.get("SYSTEMROOT", "C:\\Windows")
        self.blocked_dirs: list = list(dict.fromkeys([
            "C:\\Windows",
            "C:\\Program Files",
            "C:\\Program Files (x86)",
            sysroot,
        ]))
        self.bot_work_dir: str = ""

    def to_dict(self):
        return {
            "root_dir": self.root_dir,
            "enable_file_isolation": self.enable_file_isolation,
            "enable_network_isolation": self.enable_network_isolation,
            "enable_process_isolation": self.enable_process_isolation,
            "active_process_limit": self.active_process_limit,
            "memory_limit_mb": self.memory_limit_mb,
            "cpu_rate_limit": self.cpu_rate_limit,
            "allowed_hosts": self.allowed_hosts,
            "blocked_dirs": self.blocked_dirs,
            "bot_work_dir": self.bot_work_dir,
        }

    @classmethod
    def from_dict(cls, data):
        config = cls()
        for key, value in data.items():
            if hasattr(config, key):
                setattr(config, key, value)
        for h in [
            "api.sgroup.qq.com", "api.qq.com", "bots.qq.com",
            "wss://api.sgroup.qq.com", "wss://api.qq.com",
            "api.openai.com", "api.deepseek.com", "api.anthropic.com",
            "open.bigmodel.cn", "dashscope.aliyuncs.com",
        ]:
            if h not in config.allowed_hosts:
                config.allowed_hosts.append(h)
        return config

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        return cls()


class SandboxState:
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class SandboxManager:
    def __init__(self):
        self.config = SandboxConfig()
        self.state = SandboxState.STOPPED
        self.job_manager = JobObjectManager()
        self.fs_sandbox: Optional[FileSystemSandbox] = None
        self.net_sandbox: Optional[NetworkSandbox] = None
        self.proc_sandbox: Optional[ProcessSandbox] = None
        self.proxy_sandbox: Optional[ProxySandbox] = None

        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_monitor = threading.Event()
        self._lock = threading.Lock()
        self._on_state_change: Optional[Callable] = None
        self._on_error: Optional[Callable] = None

        self.stats = {
            "active_processes": 0,
            "total_processes": 0,
            "memory_usage_mb": 0,
            "cpu_usage_percent": 0,
            "uptime": 0,
            "file_ops_blocked": 0,
            "net_ops_blocked": 0,
        }

    def on_state_change(self, callback: Callable):
        self._on_state_change = callback

    def on_error(self, callback: Callable):
        self._on_error = callback

    def _set_state(self, new_state):
        old_state = self.state
        self.state = new_state
        if self._on_state_change:
            try:
                self._on_state_change(old_state, new_state)
            except Exception:
                pass

    def _report_error(self, message):
        logger.error(message)
        if self._on_error:
            try:
                self._on_error(message)
            except Exception:
                pass

    def start(self, root_dir: str):
        with self._lock:
            if self.state in (SandboxState.RUNNING, SandboxState.STARTING):
                logger.warning("Sandbox is already running")
                return False

            if sys.platform != "win32":
                logger.warning(
                    "SandboxQQ 沙盒隔离当前仅支持 Windows (AppContainer + Windows Firewall)。"
                    "Linux/macOS 下进程隔离依赖 Docker（需自行安装），网络/文件隔离不可用。"
                )

            self._set_state(SandboxState.STARTING)
            self.config.root_dir = root_dir

            try:
                root_path = Path(root_dir).resolve()
                root_path.mkdir(parents=True, exist_ok=True)

                # ── 进程隔离 ──
                if self.config.enable_process_isolation:
                    if self.job_manager:
                        self.job_manager.close()
                    self.job_manager = JobObjectManager()
                    self.job_manager.create_job(name=f"Sandbox_{id(self)}",
                        active_process_limit=self.config.active_process_limit,
                        memory_limit_mb=self.config.memory_limit_mb)

                    self.proc_sandbox = ProcessSandbox(
                        self.job_manager,
                        root_dir,
                        self.config.active_process_limit,
                    )
                    self.stats["total_processes"] = 0

                # ── 获取 AppContainer SID 字符串（供防火墙使用）──
                appcontainer_sid_str = ""
                if HAS_PYWIN32:
                    try:
                        appcontainer_sid_str = TokenManager.get_appcontainer_sid_string()
                    except Exception:
                        pass

                # ── 网络隔离 ──
                if self.config.enable_network_isolation and self.config.allowed_hosts:
                    self.net_sandbox = NetworkSandbox(
                        root_dir,
                        allowed_hosts=self.config.allowed_hosts,
                        appcontainer_sid_str=appcontainer_sid_str,
                    )
                    self.net_sandbox.activate()

                    # Start proxy
                    try:
                        self.proxy_sandbox = ProxySandbox(
                            allowed_hosts=self.config.allowed_hosts,
                        )
                        import asyncio, threading
                        proxy_loop = asyncio.new_event_loop()
                        proxy_thread = threading.Thread(
                            target=lambda: proxy_loop.run_until_complete(
                                self.proxy_sandbox.start()
                            ),
                            daemon=True,
                        )
                        proxy_thread.start()
                        import time
                        time.sleep(0.2)
                        if self.proxy_sandbox.proxy_url and self.proc_sandbox:
                            self.proc_sandbox.set_proxy_url(self.proxy_sandbox.proxy_url)
                            logger.info(f"Subprocess proxy: {self.proxy_sandbox.proxy_url}")
                    except Exception as e:
                        logger.warning(f"Proxy init failed (non-fatal): {e}")

                self.stats["uptime"] = time.time()
                self._start_monitor()

                self._set_state(SandboxState.RUNNING)
                logger.info(f"Sandbox started at {root_dir}")
                return True

            except Exception as e:
                self._set_state(SandboxState.ERROR)
                self._report_error(f"Failed to start sandbox: {e}")
                return False

    def stop(self):
        with self._lock:
            if self.state in (SandboxState.STOPPED, SandboxState.STOPPING):
                return
            self._set_state(SandboxState.STOPPING)

        self._stop_monitor.set()

        if self.net_sandbox:
            self.net_sandbox.deactivate()
        if self.proxy_sandbox:
            import asyncio
            try:
                asyncio.run(self.proxy_sandbox.stop())
            except Exception:
                pass
        if self.proc_sandbox:
            self.proc_sandbox.cleanup()
        if self.job_manager:
            self.job_manager.close()

        self._set_state(SandboxState.STOPPED)
        logger.info("Sandbox stopped")

    def _start_monitor(self):
        self._stop_monitor.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _monitor_loop(self):
        while not self._stop_monitor.is_set():
            try:
                with self._lock:
                    if self.state != SandboxState.RUNNING:
                        break

                    processes = []
                    if self.job_manager:
                        for pid in list(self.job_manager.processes):
                            try:
                                proc = psutil.Process(pid)
                                if proc.is_running():
                                    processes.append(proc)
                                else:
                                    self.job_manager.processes.discard(pid)
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                self.job_manager.processes.discard(pid)

                    self.stats["active_processes"] = len(processes)
                    if processes:
                        try:
                            self.stats["memory_usage_mb"] = sum(
                                p.memory_info().rss for p in processes
                            ) / (1024 * 1024)
                            self.stats["cpu_usage_percent"] = sum(
                                p.cpu_percent(interval=0.1) for p in processes
                            )
                        except Exception:
                            pass

            except Exception as e:
                logger.debug(f"Monitor error: {e}")

            self._stop_monitor.wait(2.0)

    def get_sandbox_path(self, original_path: str) -> str:
        root = Path(self.config.root_dir).resolve()
        if self.fs_sandbox:
            return self.fs_sandbox.resolve_path(original_path)
        return str(root / Path(original_path).name)

    def get_status(self) -> dict:
        status = {
            "state": self.state,
            "root_dir": self.config.root_dir,
            "stats": dict(self.stats),
            "config": self.config.to_dict(),
        }
        if self.stats["uptime"]:
            status["uptime_seconds"] = int(time.time() - self.stats["uptime"])
        else:
            status["uptime_seconds"] = 0
        return status
