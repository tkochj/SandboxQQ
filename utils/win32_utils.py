import os
import logging
import psutil

logger = logging.getLogger(__name__)

try:
    import win32job
    import win32process
    import win32security
    import win32api
    import win32con
    import win32file
    import pywintypes
    import ntsecuritycon
    HAS_PYWIN32 = True
except ImportError:
    HAS_PYWIN32 = False
    logger.warning("pywin32 not available, sandbox will use limited isolation")

class JobObjectManager:
    def __init__(self):
        self.job_handle = None
        self.processes = set()
        self._iocompletion = None

    def create_job(self, name=None, active_process_limit=0, memory_limit_mb=0):
        if not HAS_PYWIN32:
            return False
        try:
            self.job_handle = win32job.CreateJobObject(None, name)
            self._set_basic_limits(active_process_limit, memory_limit_mb)
            self._setup_completion_port()
            return True
        except Exception as e:
            logger.error(f"Failed to create job object: {e}")
            return False

    def _set_basic_limits(self, active_process_limit=0, memory_limit_mb=0, cpu_rate=0):
        info = win32job.QueryInformationJobObject(self.job_handle, win32job.JobObjectExtendedLimitInformation)
        info['BasicLimitInformation']['LimitFlags'] = 0
        flags = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        flags |= win32job.JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
        if active_process_limit > 0:
            flags |= win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            info['BasicLimitInformation']['ActiveProcessLimit'] = active_process_limit
        if memory_limit_mb > 0:
            flags |= win32job.JOB_OBJECT_LIMIT_JOB_MEMORY
            info['JobMemoryLimit'] = memory_limit_mb * 1024 * 1024
        info['BasicLimitInformation']['LimitFlags'] = flags
        win32job.SetInformationJobObject(self.job_handle, win32job.JobObjectExtendedLimitInformation, info)

    def _setup_completion_port(self):
        pass

    def assign_process(self, pid):
        if not self.job_handle:
            return False
        handle = None
        try:
            handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, pid)
            win32job.AssignProcessToJobObject(self.job_handle, handle)
            self.processes.add(pid)
            return True
        except Exception as e:
            logger.warning(f"Failed to assign process {pid} to job: {e}")
            return False
        finally:
            if handle:
                win32api.CloseHandle(handle)

    def has_process(self, pid):
        return pid in self.processes

    def terminate_all(self, exit_code=1):
        if self.job_handle:
            try:
                win32job.TerminateJobObject(self.job_handle, exit_code)
            except Exception:
                for pid in list(self.processes):
                    self._kill_process_tree(pid)
            self.processes.clear()

    def close(self):
        self.terminate_all()
        if self.job_handle:
            try:
                win32api.CloseHandle(self.job_handle)
            except Exception:
                pass
            self.job_handle = None

    @staticmethod
    def _kill_process_tree(pid):
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except Exception:
                    pass
            parent.terminate()
        except Exception:
            pass


class TokenManager:
    @staticmethod
    def create_restricted_token():
        if not HAS_PYWIN32:
            return None
        try:
            token = win32security.OpenProcessToken(
                win32api.GetCurrentProcess(),
                win32con.TOKEN_DUPLICATE | win32con.TOKEN_ASSIGN_PRIMARY |
                win32con.TOKEN_QUERY | win32con.TOKEN_ADJUST_DEFAULT |
                win32con.TOKEN_ADJUST_SESSIONID | win32con.TOKEN_ADJUST_PRIVILEGES |
                win32con.TOKEN_ADJUST_GROUPS
            )

            restricted = win32security.CreateRestrictedToken(
                token,
                0,
                [],
                [],
                [],
            )

            try:
                low_sid = win32security.CreateWellKnownSid(
                    win32security.WinLowLabelSid, None
                )
                label = win32security.TOKEN_MANDATORY_LABEL()
                label.Label.Sid = low_sid
                label.Label.Attributes = (
                    win32security.SE_GROUP_INTEGRITY
                )
                win32security.SetTokenInformation(
                    restricted,
                    win32security.TokenIntegrityLevel,
                    label
                )
            except Exception:
                pass

            return restricted
        except Exception as e:
            logger.warning(f"Failed to create restricted token: {e}")
            return None

    @staticmethod
    def get_low_integrity_token():
        return TokenManager.create_restricted_token()
