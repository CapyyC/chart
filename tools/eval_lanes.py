"""Evaluate pro-drums lane assignment (toms high/mid/floor, crash vs ride) on MDB Drums++.

Usage: python tools/eval_lanes.py DATA_DIR
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from autodrums import audio, beats, kit, transcription  # noqa: E402
from eval_mdb import f_measure, find_pairs, midi_hits  # noqa: E402

# GM note -> (lane, cymbal)
GM_LANE = {
    35: (0, False), 36: (0, False),
    37: (1, False), 38: (1, False), 40: (1, False),
    42: (2, True), 46: (2, True),
    48: (2, False), 50: (2, False),
    45: (3, False), 47: (3, False),
    41: (4, False), 43: (4, False),
    51: (3, True), 53: (3, True), 59: (3, True),
    49: (4, True), 52: (4, True), 55: (4, True), 57: (4, True),
}
NAMES = {(0, False): "kick", (1, False): "snare", (2, True): "Y cym", (2, False): "Y tom",
         (3, True): "B cym", (3, False): "B tom", (4, True): "G cym", (4, False): "G tom"}


def main() -> None:
    data = Path(sys.argv[1])
    totals = {k: np.zeros(3, int) for k in NAMES}
    confusion = Counter()
    for style, wav, mid in find_pairs(data):
        x = audio.to_mono(audio.load_audio(wav))
        hits = transcription.pick_hits(transcription.activations(x))
        b, _ = beats.track(audio.resample(x, 44100, 22050))
        med = float(np.median(np.diff(b))) if len(b) > 2 else 0.5

        def beat_len_at(t: float) -> float:
            if len(b) < 3:
                return med
            i = int(np.clip(np.searchsorted(b, t) - 1, 0, len(b) - 2))
            return float(b[i + 1] - b[i])

        gems = kit.assign_lanes(hits, x, 44100, beat_len_at)
        ref = [(t, GM_LANE[n]) for t, n in midi_hits(mid) if n in GM_LANE]
        line = []
        for key in NAMES:
            r = np.array([t for t, k in ref if k == key])
            e = np.array([g.time for g in gems if (g.lane, g.cymbal) == key])
            tp, fp, fn = f_measure(r, e)
            totals[key] += (tp, fp, fn)
            if len(r) or len(e):
                line.append(f"{NAMES[key]} {tp}/{fp}/{fn}")
        # confusion among toms and cymbals: nearest reference within 50 ms
        for g in gems:
            if g.lane == 0 or (g.lane == 1):
                continue
            cands = [(abs(t - g.time), k) for t, k in ref if abs(t - g.time) < 0.05 and k[0] >= 2]
            if cands:
                confusion[(NAMES[min(cands)[1]], NAMES[(g.lane, g.cymbal)])] += 1
        print(f"{style:12s} " + " | ".join(line), flush=True)
    print("\nlane      P      R      F    tp/fp/fn")
    for key, name in NAMES.items():
        tp, fp, fn = totals[key]
        p = tp / max(tp + fp, 1)
        r = tp / max(tp + fn, 1)
        print(f"{name:7s} {p:.3f}  {r:.3f}  {2 * p * r / max(p + r, 1e-9):.3f}  {tp}/{fp}/{fn}")
    print("\nconfusion (reference -> predicted):")
    for (a, b), c in sorted(confusion.items(), key=lambda x: -x[1]):
        print(f"  {a:6s} -> {b:6s} {c}")


if __name__ == "__main__":
    main()
