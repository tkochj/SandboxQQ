"""
已废弃 — 文件系统隔离由 Windows AppContainer ACL 内核级保证。
Python 级 monkey-patch 不安全且冗余，v3 起不再使用。
"""
import logging
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)


class FileSystemSandbox:
    """No-op stub. 文件隔离已由 AppContainer ACL 接管。"""

    def __init__(self, sandbox_root: str = "", blocked_dirs: Optional[List[str]] = None):
        self._stats: Dict[str, int] = {"blocked_count": 0, "redirected_count": 0}
        logger.info("FileSystemSandbox disabled — AppContainer ACL provides kernel-level isolation")

    def add_allowed_write_dir(self, path: str):
        pass

    def activate(self):
        pass

    def deactivate(self):
        pass

    def resolve_path(self, path: str) -> str:
        return path

    def get_stats(self) -> dict:
        return dict(self._stats)

    def list_sandbox_files(self, relative: bool = True) -> List[str]:
        return []
