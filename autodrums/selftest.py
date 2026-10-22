"""Self-test: chart a synthesised drum loop and check the result.

Used by the Windows build to verify the packaged app (models, onnxruntime, ffmpeg) works.
"""

from __future__ import annotations

import sys
import tempfile
import time
import traceback
from pathlib import Path

import numpy as np

SR = 44100


def _kick(n: int) -> np.ndarray:
    t = np.arange(n) / SR
    f = 50 + 110 * np.exp(-t * 35)
    phase = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(phase) * np.exp(-t * 9) * 0.9


def _snare(n: int, rng) -> np.ndarray:
    t = np.arange(n) / SR
    tone = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 25) * 0.4
    noise = rng.standard_normal(n) * np.exp(-t * 16) * 0.5
    return tone + noise


def _hihat(n: int, rng) -> np.ndarray:
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    noise = np.diff(np.concatenate([[0.0], noise]))  # crude high-pass
    return noise * np.exp(-t * 60) * 0.25


def make_loop(seconds: float = 32.0, bpm: float = 120.0, start: float = 1.0) -> np.ndarray:
    rng = np.random.default_rng(7)
    out = np.zeros(int(seconds * SR), dtype=np.float64)
    beat = 60.0 / bpm
    kick, snare, hat = _kick(int(0.4 * SR)), _snare(int(0.3 * SR), rng), _hihat(int(0.08 * SR), rng)
    t = start
    i = 0
    while t < seconds - 1:
        pos = int(t * SR)
        if i % 4 in (0, 2):
            out[pos:pos + len(kick)] += kick[: len(out) - pos]
        else:
            out[pos:pos + len(snare)] += snare[: len(out) - pos]
        for half in (0, 1):
            p2 = int((t + half * beat / 2) * SR)
            out[p2:p2 + len(hat)] += hat[: len(out) - p2]
        t += beat
        i += 1
    # a simple bass line so the separator has something to remove
    tt = np.arange(len(out)) / SR
    out += 0.15 * np.sin(2 * np.pi * 55 * tt) * (tt > start)
    out /= np.max(np.abs(out)) * 1.1
    return np.stack([out, out]).astype(np.float32)


def run(report: str | None = None) -> int:
    lines: list[str] = []

    def say(msg: str) -> None:
        lines.append(msg)
        try:
            print(msg, flush=True)
        except Exception:
            pass

    ok = False
    try:
        from . import audio, chartio, models
        from .pipeline import Options, generate

        for spec in models.missing_models():
            say(f"downloading {spec.filename}")
            models.ensure_model(spec.key)
        tmp = Path(tempfile.mkdtemp(prefix="autodrums-selftest-"))
        src = tmp / "Selftest Band - Drum Loop.wav"
        audio.save_audio(src, make_loop())
        say(f"ffmpeg: {audio.ffmpeg_exe()}")
        t0 = time.time()
        res = generate(str(src), Options(output_dir=tmp / "songs", separate_drums=True))
        say(f"generated in {time.time() - t0:.1f}s -> {res.folder}")
        pc = chartio.read_chart(res.folder / "notes.chart")
        bpm = pc.tempos[0][1] / 1000
        expert = pc.tracks.get("expert", [])
        lanes = {g.lane for g in expert}
        say(f"bpm={bpm:.2f} tempo_events={len(pc.tempos)} expert_notes={len(expert)} lanes={sorted(lanes)}")
        checks = {
            "song.ogg": (res.folder / "song.ogg").is_file(),
            "drums.ogg": (res.folder / "drums.ogg").is_file(),
            "song.ini": (res.folder / "song.ini").is_file(),
            "bpm~120": abs(bpm - 120) < 1.5 or abs(bpm - 240) < 3 or abs(bpm - 60) < 1,
            "notes": len(expert) >= 40,
            "kick+snare": {0, 1} <= lanes,
            "all difficulties": set(pc.tracks) == {"expert", "hard", "medium", "easy"},
        }
        for k, v in checks.items():
            say(f"  [{'ok' if v else 'FAIL'}] {k}")
        ok = all(checks.values())
    except Exception:
        say(traceback.format_exc())
    say("SELFTEST PASSED" if ok else "SELFTEST FAILED")
    if report:
        Path(report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else None))
