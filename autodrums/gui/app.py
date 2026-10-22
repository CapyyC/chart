"""GUI entry point."""

from __future__ import annotations

import os
import sys


def _redirect_output() -> None:
    """A windowed exe has no console: send stray prints to a log file instead of None."""
    if sys.stdout is None or sys.stderr is None:
        from .. import paths
        log = open(paths.user_data_dir() / "autodrums.log", "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = log
        if sys.stderr is None:
            sys.stderr = log


_window = None  # module-level so Qt, not the garbage collector, decides teardown order


def main() -> int:
    global _window
    _redirect_output()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from .icon import app_icon
    from .main_window import MainWindow
    from .theme import STYLE

    if sys.platform == "win32":
        try:  # own taskbar icon instead of python's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AutoDrums.App")
        except Exception:
            pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("AutoDrums")
    app.setStyle("Fusion")
    font = QFont("Segoe UI", 10)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(STYLE)
    app.setWindowIcon(app_icon())
    win = _window = MainWindow()
    win.show()
    smoke = os.environ.get("AUTODRUMS_SMOKE_SCREENSHOT")
    if smoke:  # used by the build to check the packaged GUI starts and renders
        from PySide6.QtCore import QTimer

        def snap():
            win.grab().save(smoke)
            win.close()
        QTimer.singleShot(3000, snap)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
