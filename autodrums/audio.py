"""Audio decoding/encoding through ffmpeg."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

from . import paths

SAMPLE_RATE = 44100


def _creationflags() -> int:
    return 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW


def ffmpeg_exe() -> str:
    exe = paths.find_tool("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg was not found. Reinstall AutoDrums or put ffmpeg on your PATH.")
    return exe


def run_quiet(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        creationflags=_creationflags(),
        **kwargs,
    )


def load_audio(path: str | Path, sr: int = SAMPLE_RATE, channels: int = 2) -> np.ndarray:
    """Decode any audio/video file to float32 of shape (channels, samples)."""
    cmd = [
        ffmpeg_exe(), "-nostdin", "-v", "error", "-i", str(path),
        "-map", "0:a:0", "-f", "f32le", "-acodec", "pcm_f32le",
        "-ac", str(channels), "-ar", str(sr), "-",
    ]
    proc = run_quiet(cmd)
    if proc.returncode != 0:
        msg = proc.stderr.decode(errors="replace").strip().splitlines()
        raise RuntimeError("Could not decode audio: " + (msg[-1] if msg else "unknown error"))
    data = np.frombuffer(proc.stdout, dtype=np.float32)
    if data.size == 0:
        raise RuntimeError("The file contains no audio.")
    return data.reshape(-1, channels).T.copy()


def save_audio(path: str | Path, audio: np.ndarray, sr: int = SAMPLE_RATE, quality: int = 7) -> None:
    """Encode (channels, samples) float32 audio. Format follows the file extension."""
    path = Path(path)
    audio = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    channels = audio.shape[0]
    codec: list[str]
    ext = path.suffix.lower()
    if ext == ".ogg":
        codec = ["-c:a", "libvorbis", "-q:a", str(quality)]
    elif ext == ".opus":
        codec = ["-c:a", "libopus", "-b:a", "160k"]
    elif ext == ".mp3":
        codec = ["-c:a", "libmp3lame", "-q:a", "2"]
    else:
        codec = ["-c:a", "pcm_s16le"]
    cmd = [
        ffmpeg_exe(), "-nostdin", "-v", "error", "-y",
        "-f", "f32le", "-ar", str(sr), "-ac", str(channels), "-i", "-",
        *codec, str(path),
    ]
    proc = subprocess.run(
        cmd,
        input=np.ascontiguousarray(audio.T).tobytes(),
        capture_output=True,
        creationflags=_creationflags(),
    )
    if proc.returncode != 0:
        raise RuntimeError("Could not encode audio: " + proc.stderr.decode(errors="replace").strip())


def to_mono(audio: np.ndarray) -> np.ndarray:
    return audio.mean(axis=0) if audio.ndim == 2 else audio


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return x
    from scipy.signal import resample_poly
    from math import gcd

    g = gcd(sr_in, sr_out)
    return resample_poly(x, sr_out // g, sr_in // g, axis=-1).astype(np.float32)


def convert_image(src: str | Path, dest: str | Path, size: int = 512) -> bool:
    """Center-crop an image to a square album cover."""
    vf = f"crop='min(iw,ih)':'min(iw,ih)',scale={size}:{size}"
    proc = run_quiet([ffmpeg_exe(), "-nostdin", "-v", "error", "-y", "-i", str(src), "-vf", vf, str(dest)])
    return proc.returncode == 0 and Path(dest).is_file()
