"""Mapping transcribed drum classes onto Clone Hero pro-drums lanes.

ADTOF gives one class for all toms and one for crash+ride, so this module:
  * estimates each tom hit's pitch and clusters the song's toms into high/mid/floor,
  * separates crashes from rides using timbre (per-song clustering) and playing pattern.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .transcription import CYMBAL, HIHAT, KICK, SNARE, TOM, Hit

# Pro drums lanes
LANE_KICK, LANE_RED, LANE_YELLOW, LANE_BLUE, LANE_GREEN = range(5)


@dataclass
class Gem:
    time: float
    lane: int
    cymbal: bool
    strength: float
    source: str  # kick, snare, hihat, ride, crash, tom_hi, tom_mid, tom_lo
    tick: int = 0


# ------------------------------------------------------------------ helpers

def _segment(x: np.ndarray, sr: int, t0: float, t1: float) -> np.ndarray:
    a = max(0, int(t0 * sr))
    b = min(len(x), int(t1 * sr))
    return x[a:b] if b > a else np.zeros(1, dtype=np.float32)


def tom_pitch(x: np.ndarray, sr: int, t: float) -> float:
    """Dominant low-frequency peak (Hz) shortly after a tom hit."""
    seg = _segment(x, sr, t + 0.012, t + 0.13)
    if len(seg) < 256:
        return np.nan
    seg = seg * np.hanning(len(seg))
    n = 1 << 15
    spec = np.abs(np.fft.rfft(seg, n))
    freqs = np.fft.rfftfreq(n, 1 / sr)
    band = (freqs >= 55) & (freqs <= 500)
    if not band.any() or spec[band].max() <= 0:
        return np.nan
    # Weight by 1/sqrt(f) slightly to resist harmonics winning over the fundamental.
    weighted = spec[band] / np.sqrt(freqs[band] / 100.0)
    k = int(np.argmax(weighted))
    idx = np.nonzero(band)[0][k]
    if 0 < idx < len(spec) - 1:
        y0, y1, y2 = np.log(spec[idx - 1:idx + 2] + 1e-12)
        d = y0 - 2 * y1 + y2
        shift = 0.5 * (y0 - y2) / d if d < 0 else 0.0
        return float(freqs[idx] + shift * (freqs[1] - freqs[0]))
    return float(freqs[idx])


def _kmeans_1d(v: np.ndarray, k: int, iters: int = 50) -> tuple[np.ndarray, np.ndarray]:
    centers = np.quantile(v, np.linspace(0.1, 0.9, k)) if k > 1 else np.array([np.median(v)])
    for _ in range(iters):
        lab = np.argmin(np.abs(v[:, None] - centers[None, :]), axis=1)
        new = np.array([v[lab == j].mean() if np.any(lab == j) else centers[j] for j in range(k)])
        if np.allclose(new, centers):
            break
        centers = new
    lab = np.argmin(np.abs(v[:, None] - centers[None, :]), axis=1)
    return centers, lab


def cluster_toms(pitches: np.ndarray, min_gap_semitones: float = 1.8) -> np.ndarray:
    """Assign each tom hit to a lane (yellow/blue/green) from its pitch."""
    n = len(pitches)
    lanes = np.full(n, LANE_BLUE)
    ok = np.isfinite(pitches)
    if ok.sum() == 0:
        return lanes
    semis = 12 * np.log2(pitches[ok] / 100.0)
    best_k, best_lab, best_centers = 1, np.zeros(ok.sum(), int), np.array([np.median(semis)])
    for k in (2, 3):
        if ok.sum() < k * 2:
            break
        centers, lab = _kmeans_1d(semis, k)
        order = np.argsort(centers)
        centers = centers[order]
        remap = np.empty(k, int)
        remap[order] = np.arange(k)
        lab = remap[lab]
        counts = np.bincount(lab, minlength=k)
        gaps = np.diff(centers)
        spread = max(np.std(semis[lab == j]) if counts[j] > 1 else 0 for j in range(k))
        if gaps.min() >= max(min_gap_semitones, 1.2 * spread) and counts.min() >= max(2, 0.04 * ok.sum()):
            best_k, best_lab, best_centers = k, lab, centers
    if best_k == 3:
        mapping = {0: LANE_GREEN, 1: LANE_BLUE, 2: LANE_YELLOW}
    elif best_k == 2:
        mapping = {0: LANE_GREEN, 1: LANE_YELLOW}
    else:
        # A single tom: floor-tom range goes to green, otherwise yellow.
        mapping = {0: LANE_GREEN if best_centers[0] < 12 * np.log2(115 / 100.0) else LANE_YELLOW}
    lanes_ok = np.array([mapping[int(j)] for j in best_lab])
    lanes[ok] = lanes_ok
    # Hits without a pitch estimate take the most common lane.
    if (~ok).any():
        lanes[~ok] = np.bincount(lanes_ok, minlength=5).argmax()
    return lanes


def _stream_flags(times: np.ndarray, beat_len: np.ndarray, min_hits: int = 4) -> np.ndarray:
    """True for hits that are part of a time-keeping pattern: >= min_hits hits, each <= ~1 beat apart."""
    n = len(times)
    flags = np.zeros(n, bool)
    if n < min_hits:
        return flags
    ioi = np.diff(times)
    i = 0
    while i < n:
        j = i
        while j < n - 1 and ioi[j] <= 1.1 * beat_len[j]:
            j += 1
        if j - i + 1 >= min_hits:
            flags[i:j + 1] = True
        i = j + 1
    return flags


def classify_cymbals(times: np.ndarray, kick_times: np.ndarray, beat_len: np.ndarray,
                     crash_on_stream_start: bool = True) -> np.ndarray:
    """Return True for ride, False for crash, for each cymbal hit.

    Rides keep time (runs of hits about a beat apart or closer); crashes are accents. The
    first hit of a run that lands with a kick is usually a crash ("crash on one, then ride").
    """
    n = len(times)
    if n == 0:
        return np.zeros(0, bool)
    ride = _stream_flags(times, beat_len)
    if crash_on_stream_start:
        for i in range(n):
            if ride[i] and (i == 0 or not ride[i - 1]):
                if len(kick_times) and np.min(np.abs(kick_times - times[i])) < 0.03:
                    ride[i] = False
    return ride


# ------------------------------------------------------------------ main

def assign_lanes(hits: list[Hit], drum_audio_mono: np.ndarray, sr: int, beat_len_at) -> list[Gem]:
    """Turn transcribed hits into lane gems. beat_len_at(t) gives the beat length in seconds."""
    by_cls = {c: [h for h in hits if h.cls == c] for c in range(5)}
    gems: list[Gem] = []
    for h in by_cls[KICK]:
        gems.append(Gem(h.time, LANE_KICK, False, h.strength, "kick"))
    for h in by_cls[SNARE]:
        gems.append(Gem(h.time, LANE_RED, False, h.strength, "snare"))
    for h in by_cls[HIHAT]:
        gems.append(Gem(h.time, LANE_YELLOW, True, h.strength, "hihat"))

    toms = by_cls[TOM]
    if toms:
        pitches = np.array([tom_pitch(drum_audio_mono, sr, h.time) for h in toms])
        lanes = cluster_toms(pitches)
        names = {LANE_YELLOW: "tom_hi", LANE_BLUE: "tom_mid", LANE_GREEN: "tom_lo"}
        for h, lane in zip(toms, lanes):
            gems.append(Gem(h.time, int(lane), False, h.strength, names[int(lane)]))

    cym = by_cls[CYMBAL]
    if cym:
        times = np.array([h.time for h in cym])
        beat_len = np.array([beat_len_at(t) for t in times])
        kk = np.array([h.time for h in by_cls[KICK]])
        ride = classify_cymbals(times, kk, beat_len)
        for h, r in zip(cym, ride):
            gems.append(Gem(h.time, LANE_BLUE if r else LANE_GREEN, True, h.strength, "ride" if r else "crash"))
    gems.sort(key=lambda g: (g.time, g.lane))
    return gems


# Priority when more than two hand gems land together (higher wins).
PRIORITY = {"snare": 1.0, "crash": 0.95, "tom_hi": 0.9, "tom_mid": 0.9, "tom_lo": 0.9, "ride": 0.8, "hihat": 0.7}


def resolve_conflicts(gems: list[Gem]) -> list[Gem]:
    """Make every chord playable: one gem per lane, at most two hand gems (+ kick)."""
    out: list[Gem] = []
    by_tick: dict[int, list[Gem]] = {}
    for g in gems:
        by_tick.setdefault(g.tick, []).append(g)
    for tick in sorted(by_tick):
        group = by_tick[tick]
        kicks = [g for g in group if g.lane == LANE_KICK]
        hands = [g for g in group if g.lane != LANE_KICK]
        # Duplicate sources on the same lane: keep the strongest.
        best: dict[tuple[int, bool], Gem] = {}
        for g in hands:
            key = (g.lane, g.cymbal)
            if key not in best or g.strength > best[key].strength:
                best[key] = g
        hands = sorted(best.values(), key=lambda g: -PRIORITY.get(g.source, 0.5) * (0.5 + g.strength))
        placed: dict[int, Gem] = {}
        for g in hands:
            if g.lane not in placed:
                placed[g.lane] = g
                continue
            # Lane taken (e.g. hi-hat and high tom together): move toms to a free tom lane.
            if not g.cymbal:
                for alt in ((LANE_BLUE, LANE_GREEN) if g.lane == LANE_YELLOW else
                            (LANE_GREEN, LANE_YELLOW) if g.lane == LANE_BLUE else (LANE_BLUE, LANE_YELLOW)):
                    if alt not in placed:
                        g.lane = alt
                        placed[alt] = g
                        break
            elif placed[g.lane].cymbal is False:
                # Cymbal outranks a tom on the same lane only if stronger; move the tom.
                tom = placed[g.lane]
                for alt in (LANE_BLUE, LANE_GREEN, LANE_YELLOW):
                    if alt not in placed and alt != g.lane:
                        tom.lane = alt
                        placed[alt] = tom
                        placed[g.lane] = g
                        break
        hands = sorted(placed.values(), key=lambda g: -PRIORITY.get(g.source, 0.5) * (0.5 + g.strength))[:2]
        if kicks:
            out.append(max(kicks, key=lambda g: g.strength))
        out.extend(sorted(hands, key=lambda g: g.lane))
    return out
