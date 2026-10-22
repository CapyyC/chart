"""Compare transcription on full mixes vs. separated drum stems using Slakh2100 test tracks.

Usage: python tools/eval_slakh.py SLAKH_DIR [--tracks N] [--seconds S]
Each track dir holds mix.flac and all_src.mid. Separated stems are cached as drums_cache.npy.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from autodrums import audio, separation, transcription  # noqa: E402
from eval_mdb import GM_TO_CLASS, f_measure  # noqa: E402


def drum_ref(mid_path: Path) -> list[tuple[float, int]]:
    import mido

    t = 0.0
    out = []
    for msg in mido.MidiFile(str(mid_path)):
        t += msg.time
        if msg.type == "note_on" and msg.velocity > 0 and msg.channel == 9:
            out.append((t, msg.note))
    return out


def prf(tp, fp, fn):
    p = tp / max(tp + fp, 1)
    r = tp / max(tp + fn, 1)
    return p, r, 2 * p * r / max(p + r, 1e-9)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--tracks", type=int, default=12)
    ap.add_argument("--seconds", type=float, default=90)
    args = ap.parse_args()

    variants = ["mix", "stem", "mean", "max"]
    totals = {v: np.zeros((5, 3), int) for v in variants}
    dirs = sorted(d for d in args.data.iterdir() if (d / "mix.flac").is_file())[: args.tracks]
    for d in dirs:
        ref = drum_ref(d / "all_src.mid")
        if len(ref) < 50:
            continue
        times = np.array([t for t, _ in ref])
        hist = np.histogram(times, bins=np.arange(0, times.max() + 10, 10))[0]
        k = max(int(args.seconds // 10), 1)
        start = int(np.argmax(np.convolve(hist, np.ones(k), "valid"))) * 10 if len(hist) >= k else 0
        x = audio.load_audio(d / "mix.flac")[:, int(start * 44100): int((start + args.seconds) * 44100)]
        cache = d / f"drums_cache_{start}_{int(args.seconds)}.npy"
        if cache.is_file():
            stem = np.load(cache)
        else:
            stem = separation.separate_drums(x)
            np.save(cache, stem)
        ref = [(t - start, n) for t, n in ref if start <= t < start + args.seconds]
        a_mix = transcription.activations(x.mean(0))
        a_stem = transcription.activations(stem.mean(0))
        acts = {"mix": a_mix, "stem": a_stem, "mean": (a_mix + a_stem) / 2, "max": np.maximum(a_mix, a_stem)}
        line = [d.name]
        for v in variants:
            hits = transcription.pick_hits(acts[v])
            for c in range(5):
                r = np.array([t for t, n in ref if GM_TO_CLASS.get(n) == c])
                e = np.array([h.time for h in hits if h.cls == c])
                totals[v][c] += f_measure(r, e)
            line.append(f"{v}:{prf(*totals[v].sum(0))[2]:.3f}")
        print(" ".join(line), flush=True)

    print("\nF-measure per class")
    print("variant  " + "  ".join(f"{n:>7s}" for n in transcription.CLASS_NAMES) + "      all")
    for v in variants:
        fs = [prf(*totals[v][c])[2] for c in range(5)]
        print(f"{v:7s}  " + "  ".join(f"{f:7.3f}" for f in fs) + f"  {prf(*totals[v].sum(0))[2]:7.3f}")
    for v in variants:
        print(v, "counts tp/fp/fn:", totals[v].tolist())


if __name__ == "__main__":
    main()
