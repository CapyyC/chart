"""Snapping detected hits onto the beat grid.

Each beat picks one subdivision (16ths, 8th/16th triplets, 32nds...) that best explains
all the hits inside it, with a small penalty for finer or triplet grids so that straight
16ths win unless the timing clearly says otherwise.
"""

from __future__ import annotations

import numpy as np

from .tempo import RESOLUTION, TempoMap

# subdivision -> penalty (seconds, added in quadrature per note)
BASE_PENALTY = {4: 0.0, 3: 0.006, 6: 0.011, 8: 0.012, 12: 0.018, 16: 0.022}
TRIPLETS = (3, 6, 12)
ERROR_CAP = 0.035


def _choose(fracs: np.ndarray, ibi: float, penalty: dict[int, float]) -> int:
    best_d, best_cost = 4, np.inf
    for d, pen in penalty.items():
        err = np.abs(fracs - np.round(fracs * d) / d) * ibi
        cost = float(np.sum(np.minimum(err, ERROR_CAP) ** 2) + len(fracs) * pen ** 2)
        if cost < best_cost - 1e-12:
            best_d, best_cost = d, cost
    return best_d


def quantize_times(times: np.ndarray, tm: TempoMap, allow_32nds: bool = True) -> np.ndarray:
    """Return integer ticks for the given times (original audio clock)."""
    times = np.asarray(times, dtype=np.float64)
    if len(times) == 0:
        return np.zeros(0, dtype=np.int64)
    pos = np.array([tm.beat_position(t) for t in times]) - tm.origin
    beat = np.floor(pos + 1.0 / 32).astype(np.int64)
    frac = pos - beat
    order = np.argsort(beat, kind="stable")
    uniq, starts = np.unique(beat[order], return_index=True)
    groups = np.split(order, starts[1:])
    bt = tm.beat_times

    def ibi_of(b: int) -> float:
        i = int(np.clip(b + tm.origin, 0, len(bt) - 2))
        return float(bt[i + 1] - bt[i])

    penalty = dict(BASE_PENALTY)
    if not allow_32nds:
        penalty.pop(8)
        penalty.pop(16)
    choice = {int(b): _choose(frac[g], ibi_of(int(b)), penalty) for b, g in zip(uniq, groups)}

    # Shuffle/swing songs: if many beats prefer triplets, make triplets cheaper everywhere.
    multi = [b for b, g in zip(uniq, groups) if len(g) >= 2]
    if multi:
        trip_share = np.mean([choice[int(b)] in TRIPLETS for b in multi])
        if trip_share > 0.35:
            swing = dict(penalty)
            for d in TRIPLETS:
                swing[d] = swing[d] * 0.3
            swing[4] = 0.006
            choice = {int(b): _choose(frac[g], ibi_of(int(b)), swing) for b, g in zip(uniq, groups)}

    ticks = np.empty(len(times), dtype=np.int64)
    for b, g in zip(uniq, groups):
        d = choice[int(b)]
        snapped = np.round(frac[g] * d) / d
        ticks[g] = np.round((b + snapped) * RESOLUTION).astype(np.int64)
    return np.maximum(ticks, 0)
