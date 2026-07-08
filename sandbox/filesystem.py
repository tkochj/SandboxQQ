import os
import sys
import io
import builtins
import logging
from pathlib import Path
from typing import List, Optional
from functools import wraps

logger = logging.getLogger(__name__)


class FileSystemSandbox:
    def __init__(self, sandbox_root: str, blocked_dirs: Optional[List[str]] = None):
        self.sandbox_root = Path(sandbox_root).resolve()
        self.blocked_dirs = [Path(d).resolve() for d in (blocked_dirs or [])]
        self._original_open = None
        self._original_os_open = None
        self._active = False
        self._stats = {"blocked_count": 0, "redirected_count": 0}

    def activate(self):
        if self._active:
            return
        self._original_open = builtins.open
        self._original_os_open = os.open

        builtins.open = self._sandboxed_open
        os.open = self._sandboxed_os_open

        self._active = True
        logger.info(f"File system sandbox activated: root={self.sandbox_root}")

    def deactivate(self):
        if not self._active:
            return
        if self._original_open:
            builtins.open = self._original_open
        if self._original_os_open:
            os.open = self._original_os_open
        self._active = False
        logger.info("File system sandbox deactivated")

    def resolve_path(self, path: str) -> str:
        p = Path(path)
        if p.is_absolute():
            return str(p)
        return str(self.sandbox_root / p)

    def _is_path_allowed(self, path: str, mode: str = "r") -> bool:
        try:
            abs_path = os.path.abspath(os.path.normpath(path))
            abs_path_obj = Path(abs_path).resolve()

            for blocked in self.blocked_dirs:
                try:
                    abs_path_obj.relative_to(blocked)
                    self._stats["blocked_count"] += 1
                    logger.warning(f"Blocked access to system path: {abs_path}")
                    return False
                except ValueError:
                    pass

            is_write = "w" in mode or "a" in mode or "+" in mode or "x" in mode
            is_read = "r" in mode or "+" in mode

            if is_write:
                try:
                    abs_path_obj.relative_to(self.sandbox_root)
                    return True
                except ValueError:
                    self._stats["blocked_count"] += 1
                    logger.warning(
                        f"Blocked write access outside sandbox: {abs_path}"
                    )
                    return False

            return True

        except Exception as e:
            logger.error(f"Error checking path permission: {e}")
            return False

    def _sandboxed_open(self, file, mode="r", *args, **kwargs):
        if isinstance(file, (int, io.IOBase)):
            return self._original_open(file, mode, *args, **kwargs)

        file_path = str(file)
        if not self._is_path_allowed(file_path, mode):
            sandbox_path = str(self.sandbox_root / Path(file_path).name)
            self._stats["redirected_count"] += 1
            logger.info(f"Redirecting {file_path} -> {sandbox_path}")
            return self._original_open(
                sandbox_path, mode, *args, **kwargs
            )
        return self._original_open(file, mode, *args, **kwargs)

    def _sandboxed_os_open(self, path, flags, mode=0o777, *args, **kwargs):
        path_str = str(path)
        access_mode = "r"
        if flags & os.O_WRONLY or flags & os.O_RDWR:
            access_mode = "w"
        if flags & os.O_CREAT or flags & os.O_TRUNC:
            access_mode = "w"
        if flags & os.O_APPEND:
            access_mode = "a"

        if not self._is_path_allowed(path_str, access_mode):
            sandbox_path = str(self.sandbox_root / Path(path_str).name)
            self._stats["redirected_count"] += 1
            logger.info(f"Redirecting os.open {path_str} -> {sandbox_path}")
            return self._original_os_open(
                sandbox_path, flags, mode, *args, **kwargs
            )
        return self._original_os_open(path, flags, mode, *args, **kwargs)

    def get_stats(self) -> dict:
        return dict(self._stats)

    def list_sandbox_files(self, relative: bool = True) -> List[str]:
        files = []
        if self.sandbox_root.exists():
            for entry in self.sandbox_root.rglob("*"):
                if entry.is_file():
                    if relative:
                        files.append(str(entry.relative_to(self.sandbox_root)))
                    else:
                        files.append(str(entry))
        return files
