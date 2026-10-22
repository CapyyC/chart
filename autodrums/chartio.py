"""Minimal .chart reader (drum tracks, tempo map) used for previews and tests."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .kit import Gem

_LINE = re.compile(r"^\s*(\d+)\s*=\s*(\w+)\s+(.*)$")
TRACKS = {"ExpertDrums": "expert", "HardDrums": "hard", "MediumDrums": "medium", "EasyDrums": "easy"}


@dataclass
class ParsedChart:
    resolution: int = 192
    song: dict[str, str] = field(default_factory=dict)
    tempos: list[tuple[int, int]] = field(default_factory=list)
    time_sigs: list[tuple[int, int, int]] = field(default_factory=list)
    sections: list[tuple[int, str]] = field(default_factory=list)
    tracks: dict[str, list[Gem]] = field(default_factory=dict)
    star_power: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    fills: dict[str, list[tuple[int, int]]] = field(default_factory=dict)

    def seconds(self, tick: float) -> float:
        t = 0.0
        last_tick, last_bpm = 0, self.tempos[0][1] if self.tempos else 120000
        for tk, bpm in self.tempos:
            if tk >= tick:
                break
            t += (tk - last_tick) / self.resolution * 60000.0 / last_bpm
            last_tick, last_bpm = tk, bpm
        return t + (tick - last_tick) / self.resolution * 60000.0 / last_bpm

    def bar_ticks(self, end_tick: int) -> list[int]:
        out = []
        sigs = self.time_sigs or [(0, 4, 4)]
        for i, (tk, num, den) in enumerate(sigs):
            stop = sigs[i + 1][0] if i + 1 < len(sigs) else end_tick
            step = max(1, int(self.resolution * num * 4 / den))
            out.extend(range(tk, stop, step))
        return out


def read_chart(path: Path) -> ParsedChart:
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    pc = ParsedChart()
    section = None
    notes: dict[str, dict[int, dict[int, bool]]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if line in ("{", "}") or not line:
            continue
        if section == "Song":
            if "=" in line:
                k, v = line.split("=", 1)
                pc.song[k.strip()] = v.strip().strip('"')
                if k.strip() == "Resolution":
                    pc.resolution = int(float(v.strip()))
            continue
        m = _LINE.match(line)
        if not m:
            continue
        tick, kind, rest = int(m.group(1)), m.group(2), m.group(3).split()
        if section == "SyncTrack":
            if kind == "B":
                pc.tempos.append((tick, int(rest[0])))
            elif kind == "TS":
                den = 2 ** int(rest[1]) if len(rest) > 1 else 4
                pc.time_sigs.append((tick, int(rest[0]), den))
        elif section == "Events" and kind == "E":
            ev = " ".join(rest).strip('"')
            if ev.startswith("section "):
                pc.sections.append((tick, ev[8:]))
        elif section in TRACKS:
            diff = TRACKS[section]
            if kind == "N":
                lane = int(rest[0])
                d = notes.setdefault(diff, {}).setdefault(tick, {})
                if lane <= 5:
                    d.setdefault(lane, False)
                elif lane in (66, 67, 68):
                    d[lane - 64] = True
            elif kind == "S":
                code, length = int(rest[0]), int(rest[1])
                if code == 2:
                    pc.star_power.setdefault(diff, []).append((tick, length))
                elif code == 64:
                    pc.fills.setdefault(diff, []).append((tick, length))
    pc.tempos.sort()
    pc.time_sigs.sort()
    for diff, by_tick in notes.items():
        gems = []
        for tick in sorted(by_tick):
            for lane, cym in sorted(by_tick[tick].items()):
                if lane > 5:
                    continue
                gems.append(Gem(pc.seconds(tick), lane, bool(cym) and lane in (2, 3, 4), 1.0, "", tick))
        pc.tracks[diff] = gems
    return pc
