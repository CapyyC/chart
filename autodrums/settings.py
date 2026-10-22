"""Persistent user settings (JSON in the app data folder)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields

from . import paths


@dataclass
class Settings:
    output_dir: str = ""
    charter: str = "AutoDrums"
    separate_drums: bool = True
    sensitivity: float = 0.5
    allow_32nds: bool = True
    cookies_browser: str = ""
    preview_difficulty: str = "expert"
    note_speed: float = 1.0
    drums_volume: int = 100
    song_volume: int = 80

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            data = json.loads(paths.settings_path().read_text(encoding="utf-8"))
            names = {f.name for f in fields(cls)}
            for k, v in data.items():
                if k in names:
                    setattr(s, k, v)
        except Exception:
            pass
        if not s.output_dir:
            s.output_dir = str(paths.default_songs_dir())
        return s

    def save(self) -> None:
        try:
            paths.settings_path().write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError:
            pass
