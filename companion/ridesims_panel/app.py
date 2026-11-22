import faulthandler
import sys
import time
import traceback

from PySide6.QtWidgets import QApplication

from . import __version__
from .profiles import data_dir
from .ui.main_window import MainWindow


def _install_crash_logging() -> None:
    """Write unhandled errors (and hard crashes) to <data folder>/crash.log instead of vanishing."""
    try:
        d = data_dir()
        d.mkdir(parents=True, exist_ok=True)
        log = open(d / "crash.log", "a", buffering=1, encoding="utf-8")
    except OSError:
        return
    log.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} v{__version__} started ---\n")
    faulthandler.enable(log)   # native crashes

    def hook(exc_type, exc, tb) -> None:
        log.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} unhandled error ---\n")
        log.write("".join(traceback.format_exception(exc_type, exc, tb)))

    sys.excepthook = hook


def main() -> int:
    _install_crash_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("RideSims Panel Companion")
    app.setApplicationVersion(__version__)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
