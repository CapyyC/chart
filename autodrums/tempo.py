"""Building a Clone Hero tempo map (tempos + time signatures) from tracked beats.

The tracked beats are cleaned, nudged towards nearby drum onsets, and fitted with a
piecewise-constant tempo (dynamic programming over segment boundaries). Songs recorded
to a click therefore get one steady BPM, while live recordings get tempo changes only
where the timing actually drifts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

RESOLUTION = 480  # ticks per quarter note


@dataclass
class TempoMap:
    beat_times: np.ndarray          # seconds (original audio clock) of beat indices 0..n-1
    origin: int                     # beat index placed at tick 0
    pad: float                      # seconds of silence to prepend to the audio
    tempos: list[tuple[int, int]] = field(default_factory=list)   # (tick, milli-BPM)
    time_sigs: list[tuple[int, int, int]] = field(default_factory=list)  # (tick, numerator, denominator)
    downbeat_ticks: list[int] = field(default_factory=list)

    def beat_position(self, t: float) -> float:
        """Fractional beat index for a time in the original audio."""
        bt = self.beat_times
        if t <= bt[0]:
            return (t - bt[0]) / (bt[1] - bt[0])
        if t >= bt[-1]:
            return len(bt) - 1 + (t - bt[-1]) / (bt[-1] - bt[-2])
        i = int(np.searchsorted(bt, t, side="right") - 1)
        return i + (t - bt[i]) / (bt[i + 1] - bt[i])

    def tick_of_beat(self, b: float) -> float:
        return (b - self.origin) * RESOLUTION

    def time_of_tick(self, tick: float) -> float:
        """Time in the original audio for a (fractional) tick."""
        b = tick / RESOLUTION + self.origin
        bt = self.beat_times
        i = int(np.clip(np.floor(b), 0, len(bt) - 2))
        return bt[i] + (b - i) * (bt[i + 1] - bt[i])

    def chart_seconds(self, tick: float) -> float:
        """Time of a tick as Clone Hero will compute it from the written tempo events."""
        t = 0.0
        last_tick, last_bpm = 0, self.tempos[0][1]
        for tk, bpm in self.tempos[1:]:
            if tk >= tick:
                break
            t += (tk - last_tick) / RESOLUTION * 60000.0 / last_bpm
            last_tick, last_bpm = tk, bpm
        return t + (tick - last_tick) / RESOLUTION * 60000.0 / last_bpm


# ---------------------------------------------------------------- beat cleanup

def clean_beats(beats: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Fix the tracker's glitches. Returns (beats, weights); inserted beats get a low weight."""
    beats = np.sort(np.asarray(beats, dtype=np.float64))
    if len(beats) < 8:
        return beats, np.ones(len(beats))
    beats = normalize_level(beats)
    return regularize(beats)


def regularize(beats: np.ndarray, tol: float = 0.3) -> tuple[np.ndarray, np.ndarray]:
    """Follow the tracked beats like a phase-locked loop.

    A tracked beat is accepted when it falls within +-tol beats of where the next beat is
    expected; beats far off the expected position are dropped, and missing beats are filled
    in from the local tempo. After several filled-in beats in a row the loop accepts a
    phase jump, so a genuine odd bar is followed rather than ignored forever.
    """
    ibi = np.diff(beats)
    local = _rolling_median(ibi, 17)
    centres = beats[:-1] + ibi / 2

    def tau_at(t: float) -> float:
        return float(np.interp(t, centres, local))

    out = [beats[0]]
    weights = [1.0]
    j = 1
    misses = 0
    while j < len(beats):
        last = out[-1]
        tau = tau_at(last)
        expected = last + tau
        width = tol if misses < 4 else 0.5
        while j < len(beats) and beats[j] < expected - width * tau:
            j += 1
        if j >= len(beats):
            break
        if beats[j] <= expected + width * tau:
            out.append(beats[j])
            weights.append(1.0)
            j += 1
            misses = 0
        else:
            out.append(expected)
            weights.append(0.15)
            misses += 1
    return np.array(out), np.array(weights)


def _weighted_median(x: np.ndarray, w: np.ndarray) -> float:
    order = np.argsort(x)
    cw = np.cumsum(w[order])
    return float(x[order][np.searchsorted(cw, cw[-1] / 2)])


def normalize_level(beats: np.ndarray) -> np.ndarray:
    """Keep one metrical level for the whole song.

    Beat trackers sometimes switch to half-time in breakdowns or double-time in fills.
    Intervals near twice the song's main beat are split, runs near half of it are thinned.
    """
    for _ in range(3):
        if len(beats) < 8:
            return beats
        ibi = np.diff(beats)
        ref = _weighted_median(ibi, ibi)
        out = [beats[0]]
        i = 0
        changed = False
        while i < len(ibi):
            r = ibi[i] / ref
            if 1.7 <= r <= 2.35:
                out.append(beats[i] + ibi[i] / 2)
                out.append(beats[i + 1])
                changed = True
                i += 1
            elif 0.4 <= r <= 0.62 and i + 1 < len(ibi) and 0.4 <= ibi[i + 1] / ref <= 0.62:
                # Two short intervals in a row: skip the middle beat.
                out.append(beats[i + 2])
                changed = True
                i += 2
            else:
                out.append(beats[i + 1])
                i += 1
        beats = np.array(out)
        if not changed:
            break
    return beats


def _rolling_median(x: np.ndarray, width: int) -> np.ndarray:
    half = width // 2
    return np.array([np.median(x[max(0, i - half): i + half + 1]) for i in range(len(x))])


def snap_to_onsets(beats: np.ndarray, onsets: np.ndarray, window: float = 0.03) -> np.ndarray:
    """Align beats with the drum onsets.

    First the whole grid is shifted by the typical beat-to-onset offset (the beat tracker
    and the drum detector use slightly different timing conventions), then each beat is
    moved to a drum onset within +-window seconds when there is one.
    """
    if len(onsets) == 0:
        return beats.copy()
    onsets = np.sort(onsets)

    def nearest(b: np.ndarray) -> np.ndarray:
        idx = np.searchsorted(onsets, b)
        lo = onsets[np.clip(idx - 1, 0, len(onsets) - 1)]
        hi = onsets[np.clip(idx, 0, len(onsets) - 1)]
        return np.where(np.abs(lo - b) <= np.abs(hi - b), lo, hi)

    near = nearest(beats)
    d = near - beats
    matched = np.abs(d) < 0.06
    shift = float(np.median(d[matched])) if matched.sum() >= 8 else 0.0
    out = beats + shift
    near = nearest(out)
    close = np.abs(near - out) <= window
    out[close] = near[close]
    return out


# --------------------------------------------------------- piecewise fitting

def _segment_fit(y: np.ndarray, w: np.ndarray, sigma: float, penalty_scale: float = 1.0) -> list[tuple[int, int]]:
    """Optimal partition of beat indices into constant-tempo segments.

    Cost of a segment = weighted SSE of a straight-line fit (time vs. beat index)
    normalised by sigma^2, plus a fixed penalty per segment.
    """
    n = len(y)
    x = np.arange(n, dtype=np.float64)
    W = np.concatenate([[0], np.cumsum(w)])
    Sx = np.concatenate([[0], np.cumsum(w * x)])
    Sy = np.concatenate([[0], np.cumsum(w * y)])
    Sxx = np.concatenate([[0], np.cumsum(w * x * x)])
    Sxy = np.concatenate([[0], np.cumsum(w * x * y)])
    Syy = np.concatenate([[0], np.cumsum(w * y * y)])
    penalty = penalty_scale * (12.0 + 2.0 * np.log(max(n, 2)))

    best = np.full(n + 1, np.inf)
    best[0] = 0.0
    prev = np.zeros(n + 1, dtype=int)
    for end in range(2, n + 1):
        starts = np.arange(0, end - 1)
        sw = W[end] - W[starts]
        sx = Sx[end] - Sx[starts]
        sy = Sy[end] - Sy[starts]
        sxx = Sxx[end] - Sxx[starts]
        sxy = Sxy[end] - Sxy[starts]
        syy = Syy[end] - Syy[starts]
        varx = sxx - sx * sx / np.maximum(sw, 1e-12)
        cov = sxy - sx * sy / np.maximum(sw, 1e-12)
        vary = syy - sy * sy / np.maximum(sw, 1e-12)
        sse = np.where(varx > 1e-12, vary - cov * cov / np.maximum(varx, 1e-12), 0.0)
        sse = np.maximum(sse, 0.0)
        total = best[starts] + sse / sigma ** 2 + penalty
        k = int(np.argmin(total))
        best[end] = total[k]
        prev[end] = starts[k]
    segs = []
    end = n
    while end > 0:
        start = prev[end]
        segs.append((start, end))
        end = start
        if end == 1:  # a lone first beat joins the following segment
            s, e = segs.pop()
            segs.append((0, e))
            break
    return segs[::-1]


def fit_beats(observed: np.ndarray, base_weights: np.ndarray | None = None, sigma: float = 0.012,
              penalty_scale: float = 1.0) -> np.ndarray:
    """Return smoothed beat times following a piecewise-constant tempo."""
    y = np.asarray(observed, dtype=np.float64)
    n = len(y)
    if n < 3:
        return y
    base = np.ones(n) if base_weights is None else np.asarray(base_weights, dtype=np.float64)
    w = base.copy()
    fitted = y
    for _ in range(2):
        segs = _segment_fit(y, w, sigma, penalty_scale)
        fitted = np.empty(n)
        for a, b in segs:
            xi = np.arange(a, b, dtype=np.float64)
            ww = w[a:b]
            if b - a == 1:
                fitted[a] = y[a]
                continue
            A = np.vstack([xi, np.ones_like(xi)]).T * np.sqrt(ww)[:, None]
            coef, *_ = np.linalg.lstsq(A, y[a:b] * np.sqrt(ww), rcond=None)
            fitted[a:b] = coef[0] * xi + coef[1]
        # Down-weight outliers (mis-tracked beats) and refit once.
        resid = np.abs(y - fitted)
        w = base * np.where(resid > 3.5 * sigma, 0.05, 1.0)
    # Guarantee monotonic beats.
    for i in range(1, n):
        if fitted[i] <= fitted[i - 1] + 0.05:
            fitted[i] = fitted[i - 1] + max(0.05, fitted[i - 1] - fitted[max(i - 2, 0)])
    return fitted


# ------------------------------------------------------------------- meter

METERS = (2, 3, 4, 5, 6, 7)
METER_COST = {4: 0.0, 3: 1.5, 2: 3.0, 6: 3.0, 5: 4.0, 7: 4.0}   # per bar, favouring common meters
SWITCH_COST = 8.0   # changing meter at a bar line
BREAK_COST = 10.0   # cutting a bar short (phase jump)


def track_bars(down_prob: np.ndarray) -> list[tuple[int, int]]:
    """Viterbi bar tracking over beats.

    down_prob[i] is the probability that beat i is a downbeat. States are
    (meter, position in bar). Returns runs [(beat_index, beats_per_bar), ...] starting
    at the first full bar; a new run starts wherever the bar length changes.
    """
    p = np.clip(np.asarray(down_prob, dtype=np.float64), 0.03, 0.97)
    n = len(p)
    if n == 0:
        return [(0, 4)]
    on, off = -np.log(p), -np.log(1 - p)
    states = [(m, k) for m in METERS for k in range(m)]
    S = len(states)
    index = {s: i for i, s in enumerate(states)}
    cost = np.array([(on[0] if k == 0 else off[0]) + METER_COST[m] * (k == 0) for m, k in states])
    back = np.zeros((n, S), dtype=np.int32)
    for i in range(1, n):
        new = np.full(S, np.inf)
        arg = np.zeros(S, dtype=np.int32)
        # Best predecessor that ends a bar (for entering position 0 of any meter).
        for si, (m, k) in enumerate(states):
            if k == 0:
                continue
            prev = index[(m, k - 1)]
            new[si] = cost[prev]
            arg[si] = prev
        for m in METERS:
            target = index[(m, 0)]
            best, best_arg = np.inf, 0
            for si, (pm, pk) in enumerate(states):
                if pk == pm - 1:
                    c = cost[si] + (0.0 if pm == m else SWITCH_COST)
                elif pk >= 1:
                    c = cost[si] + BREAK_COST
                else:
                    continue  # no one-beat bars
                if c < best:
                    best, best_arg = c, si
            new[target] = best + METER_COST[m]
            arg[target] = best_arg
        emit = np.array([on[i] if k == 0 else off[i] for _, k in states])
        cost = new + emit
        back[i] = arg
    path = np.zeros(n, dtype=np.int32)
    path[-1] = int(np.argmin(cost))
    for i in range(n - 1, 0, -1):
        path[i - 1] = back[i, path[i]]
    bar_idx = [i for i in range(n) if states[path[i]][1] == 0]
    if not bar_idx:
        return [(0, 4)]
    runs: list[tuple[int, int]] = []
    for a, b in zip(bar_idx, bar_idx[1:] + [None]):
        length = states[path[a]][0] if b is None else b - a
        if not runs or runs[-1][1] != length:
            runs.append((a, length))
    return runs


def _sample_logits(logits: np.ndarray, fps: float, times: np.ndarray) -> np.ndarray:
    out = np.full(len(times), -10.0)
    for i, t in enumerate(times):
        f = int(round(t * fps))
        a, b = max(0, f - 2), min(len(logits), f + 3)
        if b > a:
            out[i] = float(np.max(logits[a:b]))
    return out


# --------------------------------------------------------------- main entry

def build_tempo_map(beats: np.ndarray, down_logits: np.ndarray | None, onsets: np.ndarray,
                    duration: float, first_note: float | None, lead_in: float = 2.5,
                    logit_fps: float = 50.0) -> TempoMap:
    """beats: tracked beat times; down_logits: frame-wise downbeat logits (or None)."""
    beats, weights = clean_beats(beats)
    if len(beats) < 8:
        # No usable pulse: fall back to a steady 120 BPM grid.
        start = float(onsets.min()) if len(onsets) else 0.0
        beats = start + 0.5 * np.arange(int((duration - start) / 0.5) + 2)
        weights = np.ones(len(beats))
        down_logits = None

    observed = snap_to_onsets(beats, onsets)
    fitted = fit_beats(observed, weights)

    if down_logits is not None and len(down_logits):
        prob = 1.0 / (1.0 + np.exp(-_sample_logits(down_logits, logit_fps, fitted)))
    else:
        prob = np.where(np.arange(len(fitted)) % 4 == 0, 0.9, 0.1)
    runs = track_bars(prob)
    lengths = [m for _, m in runs]
    meter = max(set(lengths), key=lambda m: sum(
        (runs[i + 1][0] if i + 1 < len(runs) else len(fitted)) - runs[i][0]
        for i in range(len(runs)) if runs[i][1] == m))
    anchor = runs[0][0]
    first_ibi = float(np.median(np.diff(fitted[: min(len(fitted), 9)])))
    last_ibi = float(np.median(np.diff(fitted[-9:])))

    def beat_time(j: int) -> float:
        return float(fitted[j]) if j >= 0 else float(fitted[0] + j * first_ibi)

    # Tick 0 must be a bar line at or before time 0 (the gap becomes prepended silence),
    # and early enough to leave a lead-in before the first note.
    earliest = 0.0 if first_note is None else min(0.0, first_note - lead_in)
    k_bars = 0
    while beat_time(anchor - k_bars * meter) > earliest + 1e-9:
        k_bars += 1
    start_idx = anchor - k_bars * meter
    pre_beats = max(0, -start_idx)
    pre = fitted[0] - first_ibi * np.arange(pre_beats, 0, -1)
    post_n = int(np.ceil(max(0.0, duration - fitted[-1]) / last_ibi)) + 2 * meter
    post = fitted[-1] + last_ibi * np.arange(1, post_n + 1)
    grid = np.concatenate([pre, fitted, post])
    origin = start_idx + pre_beats
    pad = max(0.0, -float(grid[origin]))

    runs = [(s + pre_beats, m) for s, m in runs]
    tm = TempoMap(beat_times=grid, origin=origin, pad=pad)
    _write_tempos(tm)
    _write_time_sigs(tm, runs, meter)
    return tm


def _write_tempos(tm: TempoMap) -> None:
    """Tempo events (milli-BPM) with error-compensated rounding."""
    bt = tm.beat_times[tm.origin:]
    ibi = np.diff(bt)
    events: list[tuple[int, int]] = []
    # Group beats with (nearly) identical intervals into one tempo event.
    groups: list[tuple[int, int]] = []
    start = 0
    for i in range(1, len(ibi) + 1):
        if i == len(ibi) or abs(ibi[i] - ibi[start]) > 1e-6 * max(ibi[start], 1e-3) + 2e-7:
            groups.append((start, i))
            start = i
    chart_t = 0.0
    target0 = bt[0]
    for a, b in groups:
        n = b - a
        target_end = bt[b] - target0
        dur = target_end - chart_t
        mbpm = int(round(60000.0 * n / dur)) if dur > 0 else 120000
        mbpm = int(np.clip(mbpm, 1000, 1000000))
        if not events or events[-1][1] != mbpm:
            events.append((a * RESOLUTION, mbpm))
        chart_t += n * 60000.0 / mbpm
    tm.tempos = events


def _write_time_sigs(tm: TempoMap, runs: list[tuple[int, int]], meter: int) -> None:
    sigs: list[tuple[int, int, int]] = []
    downs: list[int] = []
    n_beats = len(tm.beat_times) - tm.origin
    # Bars before the first run use the base meter (they start at tick 0 by construction).
    first_start = runs[0][0] - tm.origin
    run_list = [(0, meter)] if first_start > 0 else []
    run_list += [(s - tm.origin, m) for s, m in runs if s - tm.origin >= 0]
    for idx, (s, m) in enumerate(run_list):
        end = run_list[idx + 1][0] if idx + 1 < len(run_list) else n_beats
        if not sigs or sigs[-1][1] != m:
            sigs.append((s * RESOLUTION, m, 4))
        b = s
        while b < end:
            downs.append(b * RESOLUTION)
            b += m
    tm.time_sigs = sigs
    tm.downbeat_ticks = downs
