"""Render the app icon to packaging/icon.ico (run before PyInstaller)."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from autodrums.gui.icon import render, write_ico  # noqa: E402

app = QGuiApplication(sys.argv)
here = Path(__file__).resolve().parent
write_ico(str(here / "icon.ico"))
render(256).save(str(here / "icon.png"))
print("wrote", here / "icon.ico")
