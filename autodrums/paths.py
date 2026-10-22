"""Locations of bundled resources, user data and external tools."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from . import APP_NAME


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Directory holding bundled resources (PyInstaller's _MEIPASS when frozen)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return user_data_dir() / "settings.json"


def work_dir() -> Path:
    path = user_data_dir() / "work"
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_dirs() -> list[Path]:
    """Places to look for model files, in priority order."""
    dirs = []
    env = os.environ.get("AUTODRUMS_MODELS")
    if env:
        dirs.append(Path(env))
    dirs.append(bundle_dir() / "models")
    dirs.append(user_data_dir() / "models")
    return dirs


def find_tool(name: str) -> str | None:
    """Find an external executable (ffmpeg, ffprobe, deno), preferring bundled copies."""
    exe = name + (".exe" if sys.platform == "win32" else "")
    for d in (bundle_dir() / "bin", Path(sys.executable).parent / "bin", user_data_dir() / "bin"):
        candidate = d / exe
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def documents_dir() -> Path:
    """The user's Documents folder (follows OneDrive/known-folder redirection on Windows)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD),
                            ("d4", ctypes.c_ubyte * 8)]

            # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
            fid = GUID(0xFDD39AD0, 0x238F, 0x46AF, (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(out)) == 0:
                path = Path(out.value)
                ctypes.windll.ole32.CoTaskMemFree(out)
                return path
        except Exception:
            pass
    return Path.home() / "Documents"


def default_songs_dir() -> Path:
    """Best guess at the Clone Hero songs folder."""
    home = Path.home()
    candidates = [
        documents_dir() / "Clone Hero" / "Songs",
        home / "Documents" / "Clone Hero" / "Songs",
        home / "Clone Hero" / "Songs",
        home / ".clonehero" / "Songs",
    ]
    for c in candidates:
        if c.is_dir():
            return c / APP_NAME
    return documents_dir() / "Clone Hero" / "Songs" / APP_NAME
