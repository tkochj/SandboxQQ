import os
import sys
import time
import subprocess
import logging
import threading
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


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
        restricted_token=None,
        sandbox_root: str = "",
        max_processes: int = 10,
    ):
        self.job_manager = job_manager
        self.restricted_token = restricted_token
        self.sandbox_root = Path(sandbox_root).resolve() if sandbox_root else None
        self.max_processes = max_processes
        self._processes: Dict[int, SandboxedProcess] = {}
        self._lock = threading.Lock()

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

        proc = None
        if self.restricted_token and HAS_PYWIN32:
            try:
                import win32process, win32security, win32api
                cmd_line = cmd if isinstance(cmd, str) else subprocess.list2cmdline(cmd)
                h_process = win32process.CreateProcessAsUser(
                    self.restricted_token,
                    None,
                    cmd_line,
                    None, None, False,
                    win32process.CREATE_SUSPENDED | win32process.CREATE_NEW_CONSOLE,
                    process_env,
                    work_dir,
                    win32process.STARTUPINFO(),
                )
                proc_handle, thread_handle, pid, tid = h_process
                win32process.ResumeThread(thread_handle)
                proc = subprocess.Popen(pid=pid)
                proc.stdout = None
                proc.stderr = None
                logger.info(f"Spawned with restricted token: PID {pid}")
            except Exception as e:
                logger.warning(f"Restricted token failed, fallback: {e}")

        if not proc:
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=work_dir,
                    env=process_env,
                    stdout=subprocess.PIPE if capture_output else None,
                    stderr=subprocess.PIPE if capture_output else None,
                    shell=shell,
                )
            except Exception as e:
                logger.error(f"Failed to spawn process: {e}")
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
                    import psutil
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
