import os
import sys
import logging
import psutil

logger = logging.getLogger(__name__)
IS_WINDOWS = sys.platform == "win32"

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


_SANDBOX_SID_NAME = "SandboxQQ_Container"


class TokenManager:
    @staticmethod
    def _get_appcontainer_sid():
        """Create or retrieve the AppContainer SID via userenv!CreateAppContainerProfile."""
        import ctypes
        from ctypes import wintypes

        userenv = ctypes.WinDLL("userenv")
        CreateAppContainerProfile = userenv.CreateAppContainerProfile
        CreateAppContainerProfile.restype = wintypes.HRESULT
        CreateAppContainerProfile.argtypes = [
            wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.PSID),
        ]

        name = _SANDBOX_SID_NAME
        sid_ptr = wintypes.PSID()
        hr = CreateAppContainerProfile(
            name, "SandboxQQ Container", "SandboxQQ AppContainer isolation",
            None, 0, ctypes.byref(sid_ptr),
        )
        if hr != 0:  # S_OK
            # Already exists — derive SID from name
            from ctypes import wintypes as w
            kernel32 = ctypes.WinDLL("kernel32")
            DeriveAppContainerSidFromAppContainerName = kernel32.DeriveAppContainerSidFromAppContainerName
            DeriveAppContainerSidFromAppContainerName.restype = wintypes.BOOL
            DeriveAppContainerSidFromAppContainerName.argtypes = [
                wintypes.LPCWSTR, ctypes.POINTER(wintypes.PSID),
            ]
            if not DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid_ptr)):
                logger.warning("DeriveAppContainerSidFromAppContainerName failed")
                return None
        return sid_ptr

    @staticmethod
    def _ensure_container_profile(sandbox_root: str):
        """Grant AppContainer full access to sandbox root; deny access to sensitive system dirs."""
        try:
            import string as _string_mod
            import subprocess
            import win32security

            sandbox_root = os.path.abspath(sandbox_root)
            Path(sandbox_root).mkdir(parents=True, exist_ok=True)

            sid_ptr = TokenManager._get_appcontainer_sid()
            if not sid_ptr:
                logger.warning("Cannot get AppContainer SID for ACL")
                return None
            sid_str = win32security.ConvertSidToStringSid(sid_ptr)

            # Grant full access to sandbox directory
            subprocess.run(
                ["icacls", sandbox_root, "/grant", f"{sid_str}:(OI)(CI)F", "/T", "/Q"],
                capture_output=True, timeout=30,
            )

            # Deny sensitive directories
            user_profile = os.environ.get("USERPROFILE", "")
            deny_dirs = [
                os.environ.get("SYSTEMROOT", "C:\\Windows"),
                os.environ.get("APPDATA", ""),
                os.environ.get("LOCALAPPDATA", ""),
                os.environ.get("TEMP", ""),
                os.environ.get("TMP", ""),
                "C:\\Program Files",
                "C:\\Program Files (x86)",
                "C:\\ProgramData",
            ]
            # Add specific user subdirectories (not whole Users root — preserves AppContainer profile)
            if user_profile:
                for sub in ["Documents", "Desktop", "Downloads", "Pictures", "Videos", "Music", "Favorites", "Contacts"]:
                    deny_dirs.append(os.path.join(user_profile, sub))
                deny_dirs.append(os.path.join(os.path.dirname(user_profile), "Public"))
            # Add all fixed drive roots
            if IS_WINDOWS:
                import ctypes
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                buf = ctypes.create_unicode_buffer(260)
                for letter in _string_mod.ascii_uppercase:
                    root = f"{letter}:\\"
                    if kernel32.GetDriveTypeW(root) == 3:  # DRIVE_FIXED
                        deny_dirs.append(root)

            deny_script = ""
            for d in set(deny_dirs):
                if d and os.path.exists(d):
                    deny_script += f"icacls \"{d}\" /deny \"{sid_str}:(RX,W,AD,DC,DE)\" /T /Q 2>nul & "
            if deny_script:
                subprocess.run(deny_script, shell=True, capture_output=True, timeout=60)

            logger.info(f"AppContainer profile ACL set for {sandbox_root}")
            return sid_ptr
        except Exception as e:
            logger.warning(f"Failed to set up container ACL: {e}")
            return None

    @staticmethod
    def get_container_sandbox(sandbox_root: str):
        """Public entry point: ensure AppContainer profile + ACL, return PSID pointer."""
        if not HAS_PYWIN32:
            logger.warning("pywin32 missing, cannot create AppContainer token")
            return None

        try:
            sid_ptr = TokenManager._ensure_container_profile(sandbox_root)
            if not sid_ptr:
                logger.warning("AppContainer profile creation failed")
                return None
            logger.info(f"AppContainer ready for {sandbox_root}")
            return sid_ptr
        except Exception as e:
            logger.warning(f"Failed to create AppContainer: {e}")
            return None

    @staticmethod
    def get_appcontainer_sid_string() -> str:
        """Return the AppContainer SID as a string (e.g. 'S-1-15-2-...'), or empty."""
        try:
            import win32security
            sid_ptr = TokenManager._get_appcontainer_sid()
            if not sid_ptr:
                return ""
            return win32security.ConvertSidToStringSid(sid_ptr)
        except Exception as e:
            logger.warning(f"Cannot get AppContainer SID string: {e}")
            return ""

    @staticmethod
    def create_restricted_token():
        """Fallback: create a restricted token without AppContainer."""
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

            restricted = win32security.CreateRestrictedToken(token, 0, [], [], [])

            try:
                low_sid = win32security.CreateWellKnownSid(
                    win32security.WinLowLabelSid, None
                )
                label = win32security.TOKEN_MANDATORY_LABEL()
                label.Label.Sid = low_sid
                label.Label.Attributes = win32security.SE_GROUP_INTEGRITY
                win32security.SetTokenInformation(
                    restricted, win32security.TokenIntegrityLevel, label
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
