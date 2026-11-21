import sys

from PySide6.QtWidgets import QApplication

from . import __version__
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("RideSims Panel Companion")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
