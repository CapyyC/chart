"""End-to-end: song in, Clone Hero pro drums chart folder out."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from . import audio, beats, difficulty, download, kit, paths, quantize, separation, tempo, transcription
from .chart import ChartData, SongMeta, estimate_difficulty, make_phrases, write_chart, write_ini
from .kit import Gem

SR = audio.SAMPLE_RATE


@dataclass
class Options:
    output_dir: Path
    title: str = ""
    artist: str = ""
    album: str = ""
    year: str = ""
    genre: str = ""
    charter: str = "AutoDrums"
    separate_drums: bool = True        # isolate drums: better detection + drums.ogg that mutes on misses
    sensitivity: float = 0.5           # 0..1, 0.5 = model defaults
    allow_32nds: bool = True
    difficulties: tuple[str, ...] = ("expert", "hard", "medium", "easy")
    cookies_browser: str | None = None


@dataclass
class ChartResult:
    folder: Path
    title: str
    artist: str
    bpm: float
    duration: float
    note_counts: dict[str, int]
    lane_counts: dict[str, int]
    difficulty: int
    tempo_changes: int
    elapsed: float
    gems: list[Gem] = field(default_factory=list)
    beat_ticks: list[int] = field(default_factory=list)
    downbeat_ticks: list[int] = field(default_factory=list)
    star_power: list[tuple[int, int]] = field(default_factory=list)
    tick_times: Callable[[int], float] | None = None
    song_audio: Path | None = None
    drums_audio: Path | None = None


STEPS = [
    ("download", "Getting audio", 8),
    ("separate", "Isolating drums", 50),
    ("beats", "Finding the beat", 12),
    ("transcribe", "Detecting drum hits", 10),
    ("chart", "Writing the chart", 6),
    ("export", "Exporting audio", 14),
]


class Progress:
    """Maps per-step progress to overall progress and forwards it to a callback."""

    def __init__(self, callback: Callable[[str, str, float, float], None] | None, steps: list[str]):
        self.callback = callback
        self.weights = {k: w for k, _, w in STEPS if k in steps}
        self.labels = {k: l for k, l, _ in STEPS}
        self.total = sum(self.weights.values())
        self.done = 0.0
        self.current: str | None = None

    def start(self, key: str) -> None:
        if self.current:
            self.done += self.weights.get(self.current, 0)
        self.current = key
        self.update(0.0)

    def update(self, frac: float) -> None:
        if self.callback and self.current:
            overall = (self.done + self.weights.get(self.current, 0) * min(max(frac, 0.0), 1.0)) / self.total
            self.callback(self.current, self.labels[self.current], float(frac), float(overall))

    def finish(self) -> None:
        if self.current:
            self.done += self.weights.get(self.current, 0)
            self.current = None
        if self.callback:
            self.callback("done", "Done", 1.0, 1.0)


def safe_name(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip().rstrip(".")
    return re.sub(r"\s+", " ", text)[:120] or "Untitled"


def generate(source: str, opts: Options,
             progress_cb: Callable[[str, str, float, float], None] | None = None,
             cancel: Callable[[], bool] | None = None,
             log: Callable[[str], None] | None = None) -> ChartResult:
    work = Path(tempfile.mkdtemp(prefix="job-", dir=paths.work_dir()))
    try:
        return _generate(source, opts, work, progress_cb, cancel, log)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _generate(source: str, opts: Options, work: Path,
              progress_cb: Callable[[str, str, float, float], None] | None,
              cancel: Callable[[], bool] | None,
              log: Callable[[str], None] | None) -> ChartResult:
    t_start = time.time()
    log = log or (lambda s: None)
    steps = ["download", "beats", "transcribe", "chart", "export"]
    if opts.separate_drums:
        steps.insert(1, "separate")
    prog = Progress(progress_cb, steps)

    def check_cancel():
        if cancel and cancel():
            raise InterruptedError("Cancelled")

    # 1. Audio in
    prog.start("download")
    if download.is_url(source):
        log(f"Downloading {source}")
        info = download.download(source, work, prog.update, opts.cookies_browser)
    else:
        path = Path(source)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {source}")
        info = download.local_song(path)
    check_cancel()
    title = opts.title.strip() or info.title
    artist = opts.artist.strip() or info.artist
    log(f"Song: {artist} - {title}")
    mix = audio.load_audio(info.audio_path, SR, 2)
    duration = mix.shape[1] / SR
    if duration < 5:
        raise RuntimeError("The audio is too short to chart.")
    log(f"Loaded {duration:.1f} s of audio")
    prog.update(1.0)
    check_cancel()

    # 2. Drum separation
    drums = None
    if opts.separate_drums:
        prog.start("separate")
        log("Separating the drum track (this is the slow part)...")
        drums = separation.separate_drums(mix, prog.update, cancel)
        check_cancel()

    # 3. Beats
    prog.start("beats")
    mono = audio.to_mono(mix)
    mono22 = audio.resample(mono, SR, beats.SAMPLE_RATE)
    beat_times, down_logits = beats.track(mono22, prog.update)
    log(f"Tracked {len(beat_times)} beats")
    check_cancel()

    # 4. Transcription (average of mix and isolated-drums activations when available)
    prog.start("transcribe")
    act = transcription.activations(mono)
    prog.update(0.5)
    if drums is not None:
        act = 0.5 * (act + transcription.activations(audio.to_mono(drums)))
    hits = transcription.pick_hits(act, transcription.sensitivity_thresholds(opts.sensitivity))
    log(f"Detected {len(hits)} drum hits")
    prog.update(1.0)
    check_cancel()

    # 5. Chart
    prog.start("chart")
    onset_times = np.array([h.time for h in hits if h.cls in (transcription.KICK, transcription.SNARE)])
    first_note = min((h.time for h in hits), default=None)
    tm = tempo.build_tempo_map(beat_times, down_logits, onset_times, duration, first_note,
                               logit_fps=beats.FPS)
    bpm0 = tm.tempos[0][1] / 1000.0 if tm.tempos else 120.0

    def beat_len_at(t: float) -> float:
        b = tm.beat_position(t)
        i = int(np.clip(np.floor(b), 0, len(tm.beat_times) - 2))
        return float(tm.beat_times[i + 1] - tm.beat_times[i])

    analysis_audio = audio.to_mono(drums) if drums is not None else mono
    gems = kit.assign_lanes(hits, analysis_audio, SR, beat_len_at)
    ticks = quantize.quantize_times(np.array([g.time for g in gems]), tm, opts.allow_32nds)
    for g, tk in zip(gems, ticks):
        g.tick = int(tk)
    expert = kit.resolve_conflicts(gems)
    downbeat_set = set(tm.downbeat_ticks)
    tracks = {d: difficulty.reduce(expert, d, downbeat_set) for d in opts.difficulties}
    if "expert" not in tracks:
        tracks["expert"] = expert
    data = ChartData(tempo=tm, tracks=tracks)
    make_phrases(data)
    log(f"Tempo map: {len(tm.tempos)} tempo event(s), starting at {bpm0:.2f} BPM")
    check_cancel()

    # 6. Output folder
    prog.start("export")
    folder = Path(opts.output_dir) / safe_name(f"{artist} - {title}")
    folder.mkdir(parents=True, exist_ok=True)
    for old in ("song.ogg", "drums.ogg", "notes.chart", "notes.mid"):
        (folder / old).unlink(missing_ok=True)
    pad = np.zeros((2, int(round(tm.pad * SR))), dtype=np.float32)
    if drums is not None:
        rest = mix - drums
        audio.save_audio(folder / "song.ogg", np.concatenate([pad, rest], axis=1))
        prog.update(0.5)
        audio.save_audio(folder / "drums.ogg", np.concatenate([pad, drums], axis=1))
    else:
        audio.save_audio(folder / "song.ogg", np.concatenate([pad, mix], axis=1))
    prog.update(0.9)
    has_art = False
    if info.thumbnail_path and info.thumbnail_path.is_file():
        has_art = audio.convert_image(info.thumbnail_path, folder / "album.jpg")

    length_ms = int(round((duration + tm.pad) * 1000))
    exp = tracks["expert"]
    diff = estimate_difficulty(exp, duration)
    preview_tick = 0
    if tm.downbeat_ticks:
        target = (tm.pad + duration * 0.35)
        preview_tick = min(tm.downbeat_ticks, key=lambda tk: abs(tm.chart_seconds(tk) - target))
    meta = SongMeta(
        title=title, artist=artist, album=opts.album or info.album, year=opts.year or info.year,
        genre=opts.genre or info.genre or "", charter=opts.charter or "AutoDrums",
        length_ms=length_ms, preview_ms=int(tm.chart_seconds(preview_tick) * 1000),
        has_drum_stem=drums is not None, has_album_art=has_art, source_url=info.source_url,
    )
    write_chart(folder / "notes.chart", data, meta)
    write_ini(folder / "song.ini", meta, diff)
    prog.finish()

    lane_names = {0: "kick", 1: "red", 2: "yellow", 3: "blue", 4: "green"}
    lane_counts: dict[str, int] = {}
    for g in exp:
        key = lane_names[g.lane] + (" cym" if g.cymbal else "")
        lane_counts[key] = lane_counts.get(key, 0) + 1

    beat_ticks = [i * tempo.RESOLUTION for i in range(len(tm.beat_times) - tm.origin)]
    return ChartResult(
        folder=folder, title=title, artist=artist, bpm=bpm0, duration=duration,
        note_counts={d: len(v) for d, v in tracks.items()}, lane_counts=lane_counts, difficulty=diff,
        tempo_changes=max(0, len(tm.tempos) - 1), elapsed=time.time() - t_start,
        gems=exp, beat_ticks=beat_ticks, downbeat_ticks=list(tm.downbeat_ticks),
        star_power=list(data.star_power), tick_times=tm.chart_seconds,
        song_audio=folder / "song.ogg", drums_audio=(folder / "drums.ogg") if drums is not None else None,
    )


def result_summary(r: ChartResult) -> str:
    keys = ("title", "artist", "bpm", "duration", "note_counts", "lane_counts", "difficulty", "tempo_changes", "elapsed")
    d = {k: getattr(r, k) for k in keys}
    d["folder"] = str(r.folder)
    return json.dumps(d, indent=2)
