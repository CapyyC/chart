"""Drum transcription with the ADTOF Frame_RNN model.

The model outputs frame-wise activations (100 fps) for five classes. Peaks are picked
the same way as the reference implementation (madmom's NotePeakPickingProcessor).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import maximum_filter, uniform_filter

from . import models

FPS = 100
SAMPLE_RATE = 44100
# Detections peak ~4 ms before the annotated onsets (measured on MDB Drums).
LATENCY = 0.004

KICK, SNARE, TOM, HIHAT, CYMBAL = range(5)
CLASS_NAMES = ["kick", "snare", "tom", "hihat", "cymbal"]
# Thresholds published with the model (bass drum, snare, toms, hi-hat, cymbals+ride).
DEFAULT_THRESHOLDS = np.array([0.22, 0.24, 0.32, 0.22, 0.30], dtype=np.float32)


@dataclass
class Hit:
    time: float      # seconds
    cls: int         # one of KICK..CYMBAL
    strength: float  # peak activation (0..1)


def activations(mono_44k: np.ndarray, progress=None) -> np.ndarray:
    """Run the network on mono 44.1 kHz audio. Returns (frames, 5) activations."""
    sess = models.session("adtof", progress)
    x = np.ascontiguousarray(mono_44k, dtype=np.float32)[None, :]
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak > 1.0:
        x = x / peak
    # The recurrent layers see the whole track at once, as in the reference.
    act = sess.run(["activations"], {"waveform": x})[0][0]
    return act.astype(np.float32)


def _peak_picking(act: np.ndarray, threshold: np.ndarray, pre_avg: int, post_avg: int,
                  pre_max: int, post_max: int) -> tuple[np.ndarray, np.ndarray]:
    avg_length = pre_avg + post_avg + 1
    avg_origin = int(np.floor((pre_avg - post_avg) / 2))
    mov_avg = uniform_filter(act, [avg_length, 1], mode="constant", origin=[avg_origin, 0])
    detections = act * (act >= mov_avg + threshold[None, :])
    max_length = pre_max + post_max + 1
    max_origin = int(np.floor((pre_max - post_max) / 2))
    mov_max = maximum_filter(detections, [max_length, 1], mode="constant", origin=[max_origin, 0])
    detections = detections * (detections == mov_max)
    frames, classes = np.nonzero(detections)
    return frames, classes


def _combine(times: np.ndarray, strengths: np.ndarray, delta: float) -> tuple[np.ndarray, np.ndarray]:
    """madmom combine_events(..., 'left'), keeping the strongest activation of each group."""
    if len(times) <= 1:
        return times, strengths
    delta += 1e-12
    out_t = [times[0]]
    out_s = [strengths[0]]
    for t, s in zip(times[1:], strengths[1:]):
        if t - out_t[-1] > delta:
            out_t.append(t)
            out_s.append(s)
        else:
            out_s[-1] = max(out_s[-1], s)
    return np.array(out_t), np.array(out_s)


def pick_hits(act: np.ndarray, thresholds: np.ndarray | None = None, combine: float = 0.02) -> list[Hit]:
    thr = DEFAULT_THRESHOLDS if thresholds is None else np.asarray(thresholds, dtype=np.float32)
    frames, classes = _peak_picking(act, thr, pre_avg=10, post_avg=1, pre_max=2, post_max=1)
    hits: list[Hit] = []
    for c in range(act.shape[1]):
        sel = classes == c
        f = np.sort(frames[sel])
        t = f.astype(np.float64) / FPS + LATENCY
        s = act[f, c]
        t, s = _combine(t, s, combine)
        hits.extend(Hit(float(tt), c, float(ss)) for tt, ss in zip(t, s))
    hits.sort(key=lambda h: (h.time, h.cls))
    return hits


def sensitivity_thresholds(sensitivity: float) -> np.ndarray:
    """Map a 0..1 sensitivity (0.5 = model default) to per-class thresholds."""
    # Lower thresholds pick up more (quieter) hits; higher ones only the clear ones.
    scale = float(np.interp(sensitivity, [0.0, 0.5, 1.0], [1.6, 1.0, 0.55]))
    return np.clip(DEFAULT_THRESHOLDS * scale, 0.05, 0.9)
