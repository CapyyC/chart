# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: builds dist/AutoDrums/ with AutoDrums.exe (GUI) and autodrums-cli.exe.
# Expects build_assets/models/*.onnx and build_assets/bin/{ffmpeg,deno}.exe to be present.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent
ASSETS = ROOT / "build_assets"
ICON = str(ROOT / "packaging" / "icon.ico")

datas = collect_data_files("yt_dlp_ejs")
binaries = collect_dynamic_libs("onnxruntime")
if (ASSETS / "models").is_dir():
    datas.append((str(ASSETS / "models"), "models"))
if (ASSETS / "bin").is_dir():
    binaries += [(str(p), "bin") for p in (ASSETS / "bin").iterdir() if p.suffix.lower() == ".exe"]

hiddenimports = collect_submodules("yt_dlp_ejs") + [
    "autodrums.cli",
    "autodrums.selftest",
    "autodrums.gui.app",
    "PySide6.QtMultimedia",
]

excludes = [
    "tkinter", "matplotlib", "IPython", "pytest", "mido",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets", "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
    "PySide6.QtBluetooth", "PySide6.QtLocation", "PySide6.QtPositioning", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtTextToSpeech", "PySide6.QtSpatialAudio", "PySide6.QtScxml",
    "PySide6.QtRemoteObjects", "PySide6.QtNfc", "PySide6.QtHttpServer", "PySide6.QtVirtualKeyboard",
]

a = Analysis(
    [str(ROOT / "packaging" / "gui_entry.py"), str(ROOT / "packaging" / "cli_entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

gui_scripts = [s for s in a.scripts if s[0] != "cli_entry"]
cli_scripts = [s for s in a.scripts if s[0] != "gui_entry"]

gui = EXE(
    pyz, gui_scripts, [],
    exclude_binaries=True, name="AutoDrums", icon=ICON,
    console=False, upx=False, disable_windowed_traceback=False,
)
cli = EXE(
    pyz, cli_scripts, [],
    exclude_binaries=True, name="autodrums-cli", icon=ICON,
    console=True, upx=False,
)
coll = COLLECT(gui, cli, a.binaries, a.datas, upx=False, name="AutoDrums")
