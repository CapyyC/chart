"""Download the ONNX models into a folder (used by the build to bundle them).

Usage: python tools/fetch_models.py DEST_DIR
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autodrums.models import MODELS  # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    dest = Path(sys.argv[1])
    dest.mkdir(parents=True, exist_ok=True)
    for spec in MODELS.values():
        out = dest / spec.filename
        if out.is_file() and out.stat().st_size == spec.size and sha256(out) == spec.sha256:
            print(f"ok      {spec.filename}")
            continue
        print(f"fetch   {spec.filename} ({spec.size / 1e6:.0f} MB) from {spec.repo}@{spec.revision[:8]}")
        req = urllib.request.Request(spec.url, headers={"User-Agent": "AutoDrums-build"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(out, "wb") as f:
            while chunk := resp.read(1 << 20):
                f.write(chunk)
        digest = sha256(out)
        if digest != spec.sha256:
            print(f"checksum mismatch for {spec.filename}: {digest}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
