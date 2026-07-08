import os
import sys
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sandboxqq")

# Fix Python 3.12 ProactorEventLoop._ssock GC crash (fixed in 3.12.1+)
if (3, 12) <= sys.version_info[:2] < (3, 12, 1):
    import asyncio
    if hasattr(asyncio, 'ProactorEventLoop'):
        _orig_del = asyncio.ProactorEventLoop.__del__
        def _safe_del(self):
            try:
                _orig_del(self)
            except AttributeError:
                pass
        asyncio.ProactorEventLoop.__del__ = _safe_del


def check_dependencies():
    missing = []
    try:
        import PyQt6
    except ImportError:
        missing.append("PyQt6")
    try:
        import win32api
    except ImportError:
        logger.warning(
            "pywin32 not installed - sandbox will use limited isolation."
        )
    try:
        import aiohttp
    except ImportError:
        missing.append("aiohttp")
    try:
        import psutil
    except ImportError:
        missing.append("psutil")

    if missing:
        logger.error(
            f"Missing dependencies: {', '.join(missing)}. "
            f"Install with: pip install {' '.join(missing)}"
        )
        return False
    return True


def main():
    if not check_dependencies():
        sys.exit(1)

    try:
        from PyQt6.QtWidgets import QApplication
        from gui.main_window import MainWindow

        app = QApplication(sys.argv)
        app.setApplicationName("SandboxQQ")
        app.setOrganizationName("SandboxQQ")

        window = MainWindow()
        window.show()

        exit_code = app.exec()
        sys.exit(exit_code)

    except ImportError as e:
        logger.error(f"Failed to import required modules: {e}")
        logger.error("Make sure PyQt6 is installed: pip install PyQt6")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Application error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
