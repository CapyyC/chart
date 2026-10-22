"""Model registry: locating bundled ONNX models or downloading them on first use."""

from __future__ import annotations

import hashlib
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import paths


@dataclass(frozen=True)
class ModelSpec:
    key: str
    filename: str
    repo: str
    revision: str
    sha256: str
    size: int
    description: str
    license: str

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{self.filename}"


MODELS: dict[str, ModelSpec] = {
    "adtof": ModelSpec(
        key="adtof",
        filename="adtof_frame_rnn.onnx",
        repo="thebluescreen/adtof-drums-onnx",
        revision="d0e809bb1c1b6fe8a4a00c576852117a0636ab5a",
        sha256="189ca3c2bc7339a5f0fdc0bb11069d4bcc4fafabd142e945228c368c379b6227",
        size=2171762,
        description="ADTOF Frame_RNN drum transcription (Zehren, Alunno, Bientinesi)",
        license="CC BY-NC-SA 4.0",
    ),
    "beat_this": ModelSpec(
        key="beat_this",
        filename="beat_this.onnx",
        repo="thebluescreen/beat-this-onnx",
        revision="92842057ebb781a31fcf0d638f04a098fb887313",
        sha256="ab31b5a815e2d90c6cb523e33f0ce45590fdcf80c4181a8115394d94633be14a",
        size=81837133,
        description="Beat This! beat and downbeat tracker (Foscarin, Schlueter, Widmer)",
        license="MIT",
    ),
    "demucs_drums": ModelSpec(
        key="demucs_drums",
        filename="htdemucs_ft_drums_fp16weights.onnx",
        repo="StemSplitio/htdemucs-ft-drums-onnx",
        revision="55f929d333054c69ae0e829b15e8f8826a39d6eb",
        sha256="047764dff888cfb87da917013377d4ec7a134f7419cbe486d9c339aa17975ddd",
        size=165612636,
        description="HT-Demucs FT drums specialist (Rouard, Massa, Defossez)",
        license="MIT",
    ),
}

ProgressFn = Callable[[str, float], None]

_lock = threading.Lock()


def find_model(key: str) -> Path | None:
    spec = MODELS[key]
    for d in paths.model_dirs():
        p = d / spec.filename
        if p.is_file() and p.stat().st_size == spec.size:
            return p
    return None


def missing_models() -> list[ModelSpec]:
    return [spec for key, spec in MODELS.items() if find_model(key) is None]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download_model(spec: ModelSpec, progress: ProgressFn | None = None) -> Path:
    dest_dir = paths.user_data_dir() / "models"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / spec.filename
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(spec.url, headers={"User-Agent": "AutoDrums"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or spec.size)
        done = 0
        while True:
            block = resp.read(1 << 20)
            if not block:
                break
            out.write(block)
            done += len(block)
            if progress:
                progress(f"Downloading {spec.filename}", done / max(total, 1))
    if tmp.stat().st_size != spec.size or _sha256(tmp) != spec.sha256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded {spec.filename} is corrupt (checksum mismatch). Please retry.")
    tmp.replace(dest)
    return dest


def ensure_model(key: str, progress: ProgressFn | None = None) -> Path:
    with _lock:
        path = find_model(key)
        if path is not None:
            return path
        return download_model(MODELS[key], progress)


_sessions: dict[str, object] = {}


def session(key: str, progress: ProgressFn | None = None):
    """Return a cached onnxruntime InferenceSession for a model."""
    import onnxruntime as ort

    if key in _sessions:
        return _sessions[key]
    path = ensure_model(key, progress)
    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    if key == "demucs_drums":
        # Graph optimisation of this large model needs >6 GB of RAM at load time;
        # unoptimised it peaks below 2 GB for a ~20% slower separation.
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
        opts.enable_cpu_mem_arena = False
    else:
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess = ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])
    _sessions[key] = sess
    return sess
