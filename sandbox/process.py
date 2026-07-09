import os
import sys
import time
import shutil
import subprocess
import logging
import threading
import psutil
from pathlib import Path
from typing import Optional, List, Dict

from utils.win32_utils import HAS_PYWIN32

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

def _check_docker() -> bool:
    if not IS_LINUX:
        return False
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False

HAS_DOCKER = _check_docker()


class _SandboxedProc:
    """Minimal Popen-compatible wrapper for sandboxed processes without stdout/stderr capture."""
    def __init__(self, psutil_proc, pid_val):
        self._proc = psutil_proc
        self.pid = pid_val
        self.stdout = None
        self.stderr = None
        self.returncode = None
    def communicate(self, timeout=None):
        try:
            self.returncode = self._proc.wait(timeout=timeout)
        except psutil.TimeoutExpired:
            raise subprocess.TimeoutExpired(self._proc.cmdline(), timeout)
        return (b"", b"")
    def kill(self):
        self._proc.kill()


class SandboxedProcess:
    def __init__(self, pid: int, name: str, command: str):
        self.pid = pid
        self.name = name
        self.command = command
        self.start_time = time.time()
        self.memory_mb = 0.0
        self.cpu_percent = 0.0
        self.status = "running"

    def to_dict(self):
        return {
            "pid": self.pid,
            "name": self.name,
            "command": self.command,
            "status": self.status,
        }


class ProcessSandbox:
    def __init__(
        self,
        job_manager,
        sandbox_root: str = "",
        max_processes: int = 10,
    ):
        self.job_manager = job_manager
        self.sandbox_root = Path(sandbox_root).resolve() if sandbox_root else None
        self.max_processes = max_processes
        self._processes: Dict[int, SandboxedProcess] = {}
        self._lock = threading.Lock()
        self._appcontainer_sid = None
        self._isolation_ready = False
        self._platform = "windows" if IS_WINDOWS else ("linux" if IS_LINUX else "other")

        if IS_WINDOWS and self.sandbox_root:
            if not HAS_PYWIN32:
                raise RuntimeError("Windows 沙盒隔离需要 pywin32（pip install pywin32）")
            from utils.win32_utils import TokenManager
            sid_ptr = TokenManager.get_container_sandbox(str(self.sandbox_root))
            self._appcontainer_sid = sid_ptr
            if sid_ptr:
                self._isolation_ready = True
                logger.info(f"AppContainer SID obtained for {self.sandbox_root}")
            else:
                raise RuntimeError("AppContainer 初始化失败，无法隔离进程")

        elif IS_LINUX and self.sandbox_root:
            if HAS_DOCKER:
                self._isolation_ready = True
                logger.info("Linux isolation: Docker available")
            else:
                raise RuntimeError("沙盒隔离初始化失败：Linux 下需要 Docker 来隔离子进程")

        else:
            raise RuntimeError(f"平台 {self._platform} 不支持沙盒隔离")

    def set_proxy_url(self, proxy_url: str):
        self._proxy_url = proxy_url

    def spawn(
        self,
        cmd,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        capture_output: bool = True,
        shell: bool = False,
    ) -> Optional[subprocess.Popen]:
        work_dir = cwd or (str(self.sandbox_root) if self.sandbox_root else None)

        if work_dir:
            Path(work_dir).mkdir(parents=True, exist_ok=True)

        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        if self.sandbox_root:
            process_env["SANDBOX_ROOT"] = str(self.sandbox_root)
        proxy = getattr(self, '_proxy_url', '')
        if proxy:
            process_env["HTTP_PROXY"] = proxy
            process_env["HTTPS_PROXY"] = proxy
            process_env["http_proxy"] = proxy
            process_env["https_proxy"] = proxy

        proc = None
        if IS_WINDOWS:
            # Windows 隔离链: AppContainer → 受限令牌 → 拒绝
            if self._appcontainer_sid and HAS_PYWIN32:
                try:
                    import ctypes
                    from ctypes import wintypes
                    import win32process, win32api

                    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

                    attr_list_size = wintypes.DWORD(0)
                    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(attr_list_size))
                    buf = ctypes.create_string_buffer(attr_list_size.value)
                    attr_list = ctypes.cast(buf, ctypes.c_void_p)
                    if not kernel32.InitializeProcThreadAttributeList(attr_list, 1, 0, ctypes.byref(attr_list_size)):
                        raise ctypes.WinError(ctypes.get_last_error())

                    # SECURITY_CAPABILITIES structure (16 bytes on x64)
                    class SECURITY_CAPABILITIES(ctypes.Structure):
                        _fields_ = [("CapabilitySid", ctypes.c_void_p),
                                    ("CapabilityCount", wintypes.DWORD),
                                    ("Reserved", wintypes.DWORD)]
                    sec_caps = SECURITY_CAPABILITIES(
                        CapabilitySid=self._appcontainer_sid.value if self._appcontainer_sid else 0,
                        CapabilityCount=0, Reserved=0)

                    if not kernel32.UpdateProcThreadAttribute(
                        attr_list, 0, 0x20007, ctypes.byref(sec_caps), ctypes.sizeof(sec_caps), None, None,
                    ):
                        raise ctypes.WinError(ctypes.get_last_error())

                    # STARTUPINFOEX (pywin32 may lack this type)
                    class _STARTUPINFOW(ctypes.Structure):
                        _fields_ = [("cb", wintypes.DWORD),
                                    ("lpReserved", wintypes.LPWSTR),
                                    ("lpDesktop", wintypes.LPWSTR),
                                    ("lpTitle", wintypes.LPWSTR),
                                    ("dwX", wintypes.DWORD),
                                    ("dwY", wintypes.DWORD),
                                    ("dwXSize", wintypes.DWORD),
                                    ("dwYSize", wintypes.DWORD),
                                    ("dwXCountChars", wintypes.DWORD),
                                    ("dwYCountChars", wintypes.DWORD),
                                    ("dwFillAttribute", wintypes.DWORD),
                                    ("dwFlags", wintypes.DWORD),
                                    ("wShowWindow", wintypes.WORD),
                                    ("cbReserved2", wintypes.WORD),
                                    ("lpReserved2", ctypes.c_void_p),
                                    ("hStdInput", ctypes.c_void_p),
                                    ("hStdOutput", ctypes.c_void_p),
                                    ("hStdError", ctypes.c_void_p)]
                    class _STARTUPINFOEX(ctypes.Structure):
                        _fields_ = [("StartupInfo", _STARTUPINFOW),
                                    ("lpAttributeList", ctypes.c_void_p)]
                    si = _STARTUPINFOEX()
                    si.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEX)
                    si.lpAttributeList = ctypes.cast(attr_list, ctypes.c_void_p).value
                    cmd_line = cmd if isinstance(cmd, str) else subprocess.list2cmdline(cmd)
                    # Convert env dict to null-terminated environment block
                    env_block = "\0".join(f"{k}={v}" for k, v in process_env.items()) + "\0\0"
                    env_ptr = ctypes.create_unicode_buffer(env_block)
                    pi = ctypes.create_string_buffer(24)
                    if not kernel32.CreateProcessW(
                        None, cmd_line, None, None, False,
                        0x08000000 | 0x00000004,  # CREATE_NO_WINDOW | CREATE_SUSPENDED
                        env_ptr, work_dir, ctypes.byref(si), pi,
                    ):
                        raise ctypes.WinError(ctypes.get_last_error())

                    pi_fields = ctypes.cast(pi, ctypes.POINTER(ctypes.c_void_p * 4))
                    h_thread = ctypes.c_void_p(pi_fields[0][1]).value
                    pid = pi_fields[0][2]
                    kernel32.ResumeThread(h_thread)
                    proc = _SandboxedProc(psutil.Process(pid), pid)
                    logger.info(f"Spawned in AppContainer: PID {pid}")
                except Exception as e:
                    logger.warning(f"AppContainer launch failed: {e}")
                    proc = None

            if not proc:
                logger.error("Windows 沙盒隔离失败: AppContainer 启动失败，拒绝执行")
                return None

        elif IS_LINUX and HAS_DOCKER:
            # Linux 隔离: Docker 容器
            sandbox_path = str(self.sandbox_root.resolve()) if self.sandbox_root else (cwd or os.getcwd())
            # 转换 cmd: host python → container python, host paths → /sandbox/ paths
            docker_cmd_parts = []
            for part in (cmd if isinstance(cmd, list) else [cmd]):
                p = str(part)
                if sandbox_path and p.startswith(sandbox_path):
                    docker_cmd_parts.append("/sandbox" + p[len(sandbox_path):])
                elif os.path.basename(p) in ("python", "python3", "python.exe"):
                    docker_cmd_parts.append("python")
                else:
                    docker_cmd_parts.append(p)
            docker_cmd = [
                "docker", "run", "--rm", "-i",
                "-v", f"{sandbox_path}:/sandbox:rw",
                "-w", "/sandbox",
                "--read-only",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true",
                "--network", "none",
                "--user", "nobody",
                "python:3-slim",
            ] + docker_cmd_parts
            try:
                proc = subprocess.Popen(
                    docker_cmd,
                    stdout=subprocess.PIPE if capture_output else None,
                    stderr=subprocess.PIPE if capture_output else None,
                )
                logger.info(f"Spawned in Docker container: PID {proc.pid}")
            except Exception as e:
                logger.error(f"Docker spawn failed: {e}")
                return None

        else:
            # macOS / other — 拒绝执行
            logger.error(f"平台 {self._platform} 无可用沙盒隔离，拒绝执行")
            return None

        if self.job_manager:
            try:
                self.job_manager.assign_process(proc.pid)
            except Exception as e:
                logger.warning(f"Failed to assign job: {e}")

        sp = SandboxedProcess(proc.pid, cmd[0] if isinstance(cmd, list) else cmd, str(cmd))
        with self._lock:
            self._processes[proc.pid] = sp

        logger.info(f"Spawned sandboxed process: {sp.name} (PID: {proc.pid})")
        return proc

    def spawn_python(
        self,
        code: str,
        cwd: Optional[str] = None,
    ) -> Optional[subprocess.Popen]:
        work_dir = cwd or (str(self.sandbox_root) if self.sandbox_root else None)
        if work_dir:
            Path(work_dir).mkdir(parents=True, exist_ok=True)

        cmd = [sys.executable, "-c", code]
        return self.spawn(cmd, cwd=work_dir)

    def spawn_script(
        self,
        script_path: str,
        args: Optional[List[str]] = None,
        cwd: Optional[str] = None,
    ) -> Optional[subprocess.Popen]:
        cmd = [sys.executable, script_path] + (args or [])
        return self.spawn(cmd, cwd=cwd)

    def kill(self, pid: int):
        with self._lock:
            if pid in self._processes:
                try:
                    proc = psutil.Process(pid)
                    children = proc.children(recursive=True)
                    for child in children:
                        try:
                            child.terminate()
                        except Exception:
                            pass
                    proc.terminate()
                    del self._processes[pid]
                    logger.info(f"Killed sandboxed process: {pid}")
                except Exception as e:
                    logger.warning(f"Failed to kill process {pid}: {e}")

    def kill_all(self):
        with self._lock:
            pids = list(self._processes.keys())
            for pid in pids:
                self.kill(pid)

    def cleanup(self):
        self.kill_all()
        if self.job_manager:
            self.job_manager.terminate_all()

    def list_processes(self) -> List[dict]:
        with self._lock:
            return [p.to_dict() for p in self._processes.values()]
