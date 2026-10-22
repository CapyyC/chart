"""Beat and downbeat tracking with Beat This! (ONNX), following the reference inference code."""

from __future__ import annotations

from typing import Callable

import numpy as np

from . import models

SAMPLE_RATE = 22050
HOP = 441
FPS = 50
CHUNK = 1500
BORDER = 6


def logits(mono_22k: np.ndarray, progress: Callable[[float], None] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Frame-wise beat and downbeat logits (50 fps) for a whole piece."""
    sess = models.session("beat_this")
    x = np.asarray(mono_22k, dtype=np.float32)
    if len(x) < 2048:
        x = np.pad(x, (0, 2048 - len(x)))
    n_frames = len(x) // HOP + 1
    padded = np.pad(x, (512, 512), mode="reflect")

    starts = np.arange(-BORDER, n_frames - BORDER, CHUNK - 2 * BORDER)
    if n_frames > CHUNK - 2 * BORDER:
        starts[-1] = n_frames - (CHUNK - BORDER)
    beat = np.full(n_frames, -1000.0, dtype=np.float32)
    down = np.full(n_frames, -1000.0, dtype=np.float32)

    # Keep the first prediction where chunks overlap: write in reverse order.
    order = list(enumerate(starts))[::-1]
    for k, (_, start) in enumerate(order):
        a = max(int(start), 0)
        b = min(int(start) + CHUNK, n_frames)
        pad_left = max(0, -int(start))
        pad_right = max(0, min(BORDER, int(start) + CHUNK - n_frames))
        wav = padded[a * HOP:(b - 1) * HOP + 1024]
        out_b, out_d = sess.run(
            ["beat", "downbeat"],
            {"waveform": wav[None, :], "pad_frames": np.array([pad_left, pad_right], dtype=np.int64)},
        )
        out_b = out_b[0][BORDER:-BORDER]
        out_d = out_d[0][BORDER:-BORDER]
        lo = int(start) + BORDER
        hi = int(start) + CHUNK - BORDER
        span = slice(max(lo, 0), min(hi, n_frames))
        off = span.start - lo
        beat[span] = out_b[off:off + (span.stop - span.start)]
        down[span] = out_d[off:off + (span.stop - span.start)]
        if progress:
            progress((k + 1) / len(order))
    return beat, down


def _peaks(logit: np.ndarray) -> np.ndarray:
    """Local maxima within +-3 frames with logit > 0, adjacent peaks merged, sub-frame refined."""
    from scipy.ndimage import maximum_filter1d

    mx = maximum_filter1d(logit, 7, mode="constant", cval=-1000.0)
    idx = np.nonzero((logit == mx) & (logit > 0))[0]
    merged: list[float] = []
    group: list[int] = []
    for i in idx:
        if group and i - group[-1] > 1:
            merged.append(float(np.mean(group)))
            group = []
        group.append(int(i))
    if group:
        merged.append(float(np.mean(group)))
    refined = []
    for p in merged:
        i = int(round(p))
        if p == i and 0 < i < len(logit) - 1:
            y0, y1, y2 = logit[i - 1], logit[i], logit[i + 1]
            denom = y0 - 2 * y1 + y2
            shift = 0.5 * (y0 - y2) / denom if denom < 0 else 0.0
            p = i + float(np.clip(shift, -0.5, 0.5))
        refined.append(p)
    return np.array(refined, dtype=np.float64) / FPS


def track(mono_22k: np.ndarray, progress=None) -> tuple[np.ndarray, np.ndarray]:
    """Return (beat_times in seconds, frame-wise downbeat logits at FPS)."""
    b, d = logits(mono_22k, progress)
    return _peaks(b), d
