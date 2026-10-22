"""Writing Clone Hero songs: notes.chart, song.ini and the phrase/section markers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .kit import LANE_BLUE, LANE_GREEN, LANE_KICK, LANE_YELLOW, Gem
from .tempo import RESOLUTION, TempoMap

DIFFICULTIES = ["expert", "hard", "medium", "easy"]
SECTION_NAMES = {"expert": "ExpertDrums", "hard": "HardDrums", "medium": "MediumDrums", "easy": "EasyDrums"}
CYMBAL_MARKER = {LANE_YELLOW: 66, LANE_BLUE: 67, LANE_GREEN: 68}


@dataclass
class SongMeta:
    title: str
    artist: str
    album: str = ""
    year: str = ""
    genre: str = ""
    charter: str = "AutoDrums"
    length_ms: int = 0
    preview_ms: int = 0
    has_drum_stem: bool = False
    has_album_art: bool = False
    source_url: str = ""


@dataclass
class ChartData:
    tempo: TempoMap
    tracks: dict[str, list[Gem]]
    star_power: list[tuple[int, int]] = field(default_factory=list)   # (tick, length)
    fills: list[tuple[int, int]] = field(default_factory=list)        # (tick, length)
    sections: list[tuple[int, str]] = field(default_factory=list)


# ------------------------------------------------------------- phrases

def _bars(tm: TempoMap) -> list[tuple[int, int]]:
    d = tm.downbeat_ticks
    return [(a, b - a) for a, b in zip(d, d[1:])]


def make_phrases(data: ChartData) -> None:
    """Auto-place star power phrases, drum fills (activation lanes) and practice sections."""
    expert = data.tracks["expert"]
    if not expert:
        return
    bars = _bars(data.tempo)
    note_ticks = sorted({g.tick for g in expert})
    first, last = note_ticks[0], note_ticks[-1]

    def notes_in(a: int, b: int) -> list[Gem]:
        return [g for g in expert if a <= g.tick < b]

    crash_ticks = {g.tick for g in expert if g.lane == LANE_GREEN and g.cymbal}
    playable_bars = [(i, s, n) for i, (s, n) in enumerate(bars) if s + n > first and s <= last]

    # Sections: start where a new part begins (a crash on a bar line), every 4-16 bars.
    sections: list[tuple[int, str]] = []
    last_start = None
    for i, s, _n in playable_bars:
        if last_start is None:
            sections.append((s, "Part 1"))
            last_start = i
            continue
        since = i - last_start
        if (since >= 4 and s in crash_ticks and since % 2 == 0) or since >= 16:
            sections.append((s, f"Part {len(sections) + 1}"))
            last_start = i
    data.sections = sections

    # Star power: a one-bar phrase roughly every 12 bars, on bars with enough notes.
    sp: list[tuple[int, int]] = []
    pos = 3
    while pos < len(playable_bars):
        _, s, n = playable_bars[pos]
        if len(notes_in(s, s + n)) >= 4:
            sp.append((s, n))
            pos += 12
        else:
            pos += 1
    data.star_power = sp

    # Drum fills (star power activation): half a bar leading into a bar line, preferably one
    # with a crash. Without a crash, any downbeat chord works once enough bars have passed.
    fills: list[tuple[int, int]] = []
    last_fill_bar = -999
    sp_ranges = [(a, a + b) for a, b in sp]
    downbeat_chords = {g.tick for g in expert if g.lane != 0 and g.cymbal}
    for j, (i, s, _n) in enumerate(playable_bars):
        since = i - last_fill_bar
        if j < 6 or since < 8:
            continue
        if not (s in crash_ticks or (since >= 12 and s in downbeat_chords)):
            continue
        prev_start = bars[i - 1][0] if i > 0 else 0
        start = prev_start + (s - prev_start) // 2  # half-bar fill window
        if any(a < s + 1 and start < b for a, b in sp_ranges):
            continue
        if len(notes_in(start, s + 1)) < 2:
            continue
        fills.append((start, s + 1 - start))
        last_fill_bar = i
    data.fills = fills


# ------------------------------------------------------------- writers

def _q(s: str) -> str:
    return s.replace('"', "'").replace("\n", " ").strip()


def write_chart(path: Path, data: ChartData, meta: SongMeta) -> None:
    tm = data.tempo
    lines = ["[Song]", "{"]
    lines += [
        f'  Name = "{_q(meta.title)}"',
        f'  Artist = "{_q(meta.artist)}"',
        f'  Charter = "{_q(meta.charter)}"',
        f'  Album = "{_q(meta.album)}"',
        f'  Year = ", {_q(meta.year)}"',
        "  Offset = 0",
        f"  Resolution = {RESOLUTION}",
        '  Player2 = bass',
        "  Difficulty = 0",
        f"  PreviewStart = {meta.preview_ms / 1000:.3f}",
        "  PreviewEnd = 0",
        f'  Genre = "{_q(meta.genre)}"',
        '  MediaType = "cd"',
        '  MusicStream = "song.ogg"',
    ]
    if meta.has_drum_stem:
        lines.append('  DrumStream = "drums.ogg"')
    lines += ["}", "[SyncTrack]", "{"]
    sync: list[tuple[int, int, str]] = []
    for tick, num, den in tm.time_sigs:
        exp = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4}.get(den, 2)
        sync.append((tick, 0, f"TS {num}" if exp == 2 else f"TS {num} {exp}"))
    for tick, mbpm in tm.tempos:
        sync.append((tick, 1, f"B {mbpm}"))
    for tick, _, text in sorted(sync):
        lines.append(f"  {tick} = {text}")
    lines += ["}", "[Events]", "{"]
    for tick, name in data.sections:
        lines.append(f'  {tick} = E "section {_q(name)}"')
    lines.append("}")

    for diff in DIFFICULTIES:
        gems = data.tracks.get(diff) or []
        if not gems:
            continue
        events: list[tuple[int, int, str]] = []
        for g in gems:
            events.append((g.tick, 0, f"N {g.lane} 0"))
            if g.cymbal and g.lane in CYMBAL_MARKER:
                events.append((g.tick, 0, f"N {CYMBAL_MARKER[g.lane]} 0"))
        ticks = sorted({g.tick for g in gems})

        def has_notes(a: int, length: int) -> bool:
            import bisect
            k = bisect.bisect_left(ticks, a)
            return k < len(ticks) and ticks[k] < a + length

        for tick, length in data.star_power:
            if has_notes(tick, length):
                events.append((tick, 1, f"S 2 {length}"))
        for tick, length in data.fills:
            if has_notes(tick, length):
                events.append((tick, 1, f"S 64 {length}"))
        lines += [f"[{SECTION_NAMES[diff]}]", "{"]
        for tick, _, text in sorted(events, key=lambda e: (e[0], e[1], e[2])):
            lines.append(f"  {tick} = {text}")
        lines.append("}")
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8-sig")


def estimate_difficulty(expert: list[Gem], length_s: float) -> int:
    if not expert or length_s <= 0:
        return 0
    ticks = {g.tick for g in expert}
    nps = len(ticks) / max(length_s, 1.0)
    kicks = sum(1 for g in expert if g.lane == LANE_KICK) / max(length_s, 1.0)
    score = nps + 0.5 * kicks
    for level, limit in enumerate([1.5, 2.5, 3.5, 4.7, 6.0, 7.5]):
        if score < limit:
            return level
    return 6


def write_ini(path: Path, meta: SongMeta, difficulty: int) -> None:
    lines = [
        "[song]",
        f"name = {meta.title}",
        f"artist = {meta.artist}",
        f"album = {meta.album}",
        f"genre = {meta.genre}",
        f"year = {meta.year}",
        f"charter = {meta.charter}",
        f"song_length = {meta.length_ms}",
        f"preview_start_time = {meta.preview_ms}",
        f"diff_drums = {difficulty}",
        f"diff_drums_real = {difficulty}",
        "diff_guitar = -1",
        "diff_bass = -1",
        "diff_keys = -1",
        "diff_band = -1",
        "pro_drums = True",
        "five_lane_drums = False",
        "delay = 0",
        f"loading_phrase = Auto-charted by AutoDrums {__version__}",
        "modchart = 0",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
