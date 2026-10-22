"""Command line interface: python -m autodrums chart <url-or-file> [options]."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="autodrums", description="Automatic Clone Hero pro drums charts")
    ap.add_argument("--version", action="version", version=f"AutoDrums {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chart", help="chart a YouTube link or audio file")
    c.add_argument("source", help="YouTube (or other) URL, or path to an audio file")
    c.add_argument("-o", "--output", type=Path, default=None, help="songs folder (default: Clone Hero songs/AutoDrums)")
    c.add_argument("--title")
    c.add_argument("--artist")
    c.add_argument("--charter", default="AutoDrums")
    c.add_argument("--no-separation", action="store_true", help="skip drum isolation (faster, no drums.ogg)")
    c.add_argument("--sensitivity", type=float, default=0.5, help="0..1, higher = more notes (default 0.5)")
    c.add_argument("--no-32nds", action="store_true")
    c.add_argument("--cookies-from-browser", default=None, help="e.g. chrome, firefox, edge")
    sub.add_parser("models", help="download the AI models now")
    st = sub.add_parser("selftest", help="chart a generated test song and verify the output")
    st.add_argument("--report", default=None, help="also write the results to this file")
    args = ap.parse_args(argv)

    if args.cmd == "models":
        from . import models
        for spec in models.missing_models():
            print(f"Downloading {spec.filename} ...")
            models.ensure_model(spec.key, lambda msg, f: print(f"\r  {f * 100:5.1f}%", end=""))
            print()
        print("All models present.")
        return 0
    if args.cmd == "selftest":
        from .selftest import run
        return run(args.report)

    from .pipeline import Options, generate, result_summary

    out = args.output or paths.default_songs_dir()
    opts = Options(
        output_dir=out, title=args.title or "", artist=args.artist or "", charter=args.charter,
        separate_drums=not args.no_separation, sensitivity=args.sensitivity,
        allow_32nds=not args.no_32nds, cookies_browser=args.cookies_from_browser,
    )
    last = [""]

    def progress(key, label, frac, overall):
        line = f"[{overall * 100:5.1f}%] {label} {frac * 100:3.0f}%"
        if line != last[0]:
            print("\r" + line.ljust(60), end="", flush=True)
            last[0] = line

    result = generate(args.source, opts, progress, log=lambda s: print("\r" + s.ljust(60)))
    print()
    print(result_summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
