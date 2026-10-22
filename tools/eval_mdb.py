"""Evaluate transcription accuracy against MDB Drums++ (drum-only audio + MIDI annotations).

Usage: python tools/eval_mdb.py DATA_DIR [--sens 0.5]
DATA_DIR holds audio/*.wav and midi/*.mid from the MDBDrums++ dataset.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autodrums import audio, transcription  # noqa: E402

# General MIDI drum notes -> ADTOF's 5 classes.
GM_TO_CLASS = {
    35: 0, 36: 0,
    37: 1, 38: 1, 40: 1,
    41: 2, 43: 2, 45: 2, 47: 2, 48: 2, 50: 2,
    42: 3, 44: 3, 46: 3,
    49: 4, 51: 4, 52: 4, 53: 4, 55: 4, 57: 4, 59: 4,
}


def midi_hits(path: Path) -> list[tuple[float, int]]:
    import mido

    mid = mido.MidiFile(str(path))
    out = []
    t = 0.0
    for msg in mid:  # iterating a MidiFile yields messages with delta times in seconds
        t += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            out.append((t, msg.note))
    return out


def f_measure(ref: np.ndarray, est: np.ndarray, tol: float = 0.05) -> tuple[int, int, int]:
    """Greedy one-to-one matching within +-tol seconds. Returns (tp, fp, fn)."""
    ref = np.sort(ref)
    est = np.sort(est)
    used = np.zeros(len(est), bool)
    tp = 0
    pairs = []
    for i, r in enumerate(ref):
        lo = np.searchsorted(est, r - tol)
        hi = np.searchsorted(est, r + tol, side="right")
        for j in range(lo, hi):
            pairs.append((abs(est[j] - r), i, j))
    pairs.sort()
    used_ref = set()
    for _, i, j in pairs:
        if i in used_ref or used[j]:
            continue
        used_ref.add(i)
        used[j] = True
        tp += 1
    return tp, len(est) - tp, len(ref) - tp


def find_pairs(data: Path) -> list[tuple[str, Path, Path]]:
    pairs = []
    for mid in sorted((data / "midi").glob("*.mid")):
        stem = mid.stem.replace("_Drum", "")
        style = stem.replace("MusicDelta_", "")
        cands = list((data / "audio").glob(f"MusicDelta_{style}*_Drum.wav"))
        if not cands:
            cands = [w for w in (data / "audio").glob("*.wav") if style[:4] in w.name]
        if cands:
            pairs.append((style, cands[0], mid))
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--sens", type=float, default=0.5)
    ap.add_argument("--no-pedal", action="store_true", help="ignore hi-hat pedal (44) in references")
    args = ap.parse_args()

    thr = transcription.sensitivity_thresholds(args.sens)
    totals = np.zeros((5, 3), int)
    for style, wav, mid in find_pairs(args.data):
        x = audio.to_mono(audio.load_audio(wav))
        act = transcription.activations(x)
        hits = transcription.pick_hits(act, thr)
        ref = midi_hits(mid)
        row = []
        for c in range(5):
            r = np.array([t for t, n in ref if GM_TO_CLASS.get(n) == c and not (args.no_pedal and n == 44)])
            e = np.array([h.time for h in hits if h.cls == c])
            tp, fp, fn = f_measure(r, e)
            totals[c] += (tp, fp, fn)
            row.append(f"{transcription.CLASS_NAMES[c][:4]} {tp:3d}/{fp:3d}/{fn:3d}")
        print(f"{style:12s} " + " | ".join(row))
    print("\nclass     P      R      F    (tp/fp/fn)")
    allc = totals.sum(0)
    for c in range(5):
        tp, fp, fn = totals[c]
        p = tp / max(tp + fp, 1)
        r = tp / max(tp + fn, 1)
        f = 2 * p * r / max(p + r, 1e-9)
        print(f"{transcription.CLASS_NAMES[c]:7s} {p:.3f}  {r:.3f}  {f:.3f}  ({tp}/{fp}/{fn})")
    tp, fp, fn = allc
    p, r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    print(f"{'all':7s} {p:.3f}  {r:.3f}  {2 * p * r / max(p + r, 1e-9):.3f}")


if __name__ == "__main__":
    main()
