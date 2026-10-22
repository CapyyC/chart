"""Drum stem separation with the HT-Demucs FT drums specialist (ONNX)."""

from __future__ import annotations

from typing import Callable

import numpy as np

from . import models

SAMPLE_RATE = 44100
SEGMENT = 343980  # 7.8 s, fixed in the exported graph
OVERLAP = 0.25


def _transition_window(n: int) -> np.ndarray:
    # Triangular weighting as in demucs.apply (transition_power=1).
    t = np.arange(n, dtype=np.float32)
    w = np.minimum(t + 1, n - t)
    return (w / w.max()).astype(np.float32)


def separate_drums(mix: np.ndarray, progress: Callable[[float], None] | None = None,
                   cancel: Callable[[], bool] | None = None) -> np.ndarray:
    """Return the drums stem for a stereo 44.1 kHz mix of shape (2, samples)."""
    sess = models.session("demucs_drums")
    if mix.shape[0] == 1:
        mix = np.repeat(mix, 2, axis=0)
    mix = mix[:2].astype(np.float32)
    length = mix.shape[1]

    # Global normalisation, as demucs.separate does.
    ref = mix.mean(axis=0)
    mean, std = float(ref.mean()), float(ref.std()) + 1e-8
    x = (mix - mean) / std

    stride = int((1 - OVERLAP) * SEGMENT)
    offsets = list(range(0, max(length - SEGMENT, 0) + stride, stride)) or [0]
    if offsets[-1] + SEGMENT < length:
        offsets.append(length - SEGMENT)
    window = _transition_window(SEGMENT)
    out = np.zeros((2, length), dtype=np.float32)
    weight = np.zeros(length, dtype=np.float32)

    for i, start in enumerate(offsets):
        if cancel and cancel():
            raise InterruptedError
        chunk = x[:, start:start + SEGMENT]
        n = chunk.shape[1]
        if n < SEGMENT:
            chunk = np.pad(chunk, ((0, 0), (0, SEGMENT - n)))
        stems = sess.run(["stems"], {"mix": chunk[None]})[0][0]
        drums = stems[0, :, :n]
        w = window[:n] if n == SEGMENT else _transition_window(n)
        out[:, start:start + n] += drums * w
        weight[start:start + n] += w
        if progress:
            progress((i + 1) / len(offsets))

    out /= np.maximum(weight, 1e-8)
    return out * std + mean
