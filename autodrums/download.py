"""Fetching audio and metadata from YouTube (or any site yt-dlp supports) and local files."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import paths
from .audio import _creationflags

YTDLP_EXE_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"


@dataclass
class SongInfo:
    audio_path: Path
    title: str = "Unknown Song"
    artist: str = "Unknown Artist"
    album: str = ""
    year: str = ""
    genre: str = ""
    thumbnail_path: Path | None = None
    source_url: str = ""
    extra: dict = field(default_factory=dict)


def is_url(text: str) -> bool:
    return bool(re.match(r"^\s*https?://", text or ""))


_JUNK = re.compile(
    r"\s*[\(\[][^\)\]]*(official|video|audio|lyric|lyrics|visualizer|hd|hq|4k|remaster|"
    r"music video|mv|full album|explicit|clean)[^\)\]]*[\)\]]",
    re.IGNORECASE,
)


def clean_title(title: str) -> str:
    title = _JUNK.sub("", title)
    title = re.sub(r"\s*\|.*$", "", title)
    return re.sub(r"\s{2,}", " ", title).strip(" -_") or title


def guess_artist_title(info: dict) -> tuple[str, str]:
    artist = info.get("artist") or info.get("creator") or ""
    track = info.get("track") or ""
    if artist and track:
        return artist.split(",")[0].strip(), track.strip()
    raw = clean_title(info.get("title") or "")
    for sep in (" - ", " – ", " — ", " -- ", ": "):
        if sep in raw:
            a, t = raw.split(sep, 1)
            return a.strip(), clean_title(t)
    uploader = (info.get("channel") or info.get("uploader") or "Unknown Artist")
    uploader = re.sub(r"\s*-\s*Topic$|VEVO$|\s*Official$", "", uploader).strip()
    return uploader or "Unknown Artist", raw or "Unknown Song"


def _updated_ytdlp_exe() -> Path | None:
    p = paths.user_data_dir() / "bin" / ("yt-dlp.exe" if sys.platform == "win32" else "yt-dlp")
    return p if p.is_file() else None


def update_downloader(progress: Callable[[str, float], None] | None = None) -> str:
    """Download the latest standalone yt-dlp so YouTube changes can be picked up without reinstalling."""
    if sys.platform != "win32":
        raise RuntimeError("Run 'pip install -U \"yt-dlp[default]\"' to update the downloader.")
    dest = paths.user_data_dir() / "bin" / "yt-dlp.exe"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(YTDLP_EXE_URL, headers={"User-Agent": "AutoDrums"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if progress and total:
                progress("Updating downloader", done / total)
    tmp.replace(dest)
    proc = subprocess.run([str(dest), "--version"], capture_output=True, text=True, creationflags=_creationflags())
    return proc.stdout.strip()


def downloader_version() -> str:
    exe = _updated_ytdlp_exe()
    if exe:
        proc = subprocess.run([str(exe), "--version"], capture_output=True, text=True, creationflags=_creationflags())
        return proc.stdout.strip() + " (updated)"
    try:
        from yt_dlp.version import __version__
        return __version__
    except Exception:  # pragma: no cover
        return "unavailable"


class _QuietLogger:
    """Collect yt-dlp messages instead of printing them (a windowed app has no console)."""

    def __init__(self):
        self.errors: list[str] = []

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        self.errors.append(msg)


def _common_opts(out_dir: Path) -> dict:
    opts: dict = {
        "logger": _QuietLogger(),
        "format": "bestaudio[acodec!=none]/bestaudio/best",
        "outtmpl": str(out_dir / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "writethumbnail": True,
        "retries": 5,
        "fragment_retries": 5,
        "overwrites": True,
    }
    ffmpeg = paths.find_tool("ffmpeg")
    if ffmpeg:
        opts["ffmpeg_location"] = str(Path(ffmpeg).parent)
    deno = paths.find_tool("deno")
    if deno:
        opts["js_runtimes"] = {"deno": {"path": deno}}
    return opts


def _download_with_module(url: str, out_dir: Path, progress, cookies_browser: str | None) -> dict:
    import yt_dlp

    def hook(d):
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                progress(d.get("downloaded_bytes", 0) / total)

    opts = _common_opts(out_dir)
    opts["progress_hooks"] = [hook]
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.sanitize_info(info)


def _download_with_exe(exe: Path, url: str, out_dir: Path, progress, cookies_browser: str | None) -> dict:
    cmd = [
        str(exe), "--no-playlist", "--newline", "--no-warnings", "--force-overwrites",
        "-f", "bestaudio[acodec!=none]/bestaudio/best", "-o", str(out_dir / "source.%(ext)s"),
        "--write-thumbnail", "--print-json", "--no-simulate",
        "--progress-template", "download:PROGRESS %(progress._percent_str)s",
    ]
    ffmpeg = paths.find_tool("ffmpeg")
    if ffmpeg:
        cmd += ["--ffmpeg-location", str(Path(ffmpeg).parent)]
    deno = paths.find_tool("deno")
    if deno:
        cmd += ["--js-runtimes", f"deno:{deno}"]
    if cookies_browser:
        cmd += ["--cookies-from-browser", cookies_browser]
    cmd.append(url)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", creationflags=_creationflags())
    info = None
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("PROGRESS"):
            m = re.search(r"([\d.]+)%", line)
            if m and progress:
                progress(float(m.group(1)) / 100)
        elif line.startswith("{"):
            info = json.loads(line)
    err = proc.stderr.read() if proc.stderr else ""
    if proc.wait() != 0 or info is None:
        raise RuntimeError(err.strip().splitlines()[-1] if err.strip() else "Download failed")
    return info


def download(url: str, out_dir: Path, progress: Callable[[float], None] | None = None,
             cookies_browser: str | None = None) -> SongInfo:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("source.*"):
        old.unlink()
    exe = _updated_ytdlp_exe()
    try:
        if exe:
            info = _download_with_exe(exe, url, out_dir, progress, cookies_browser)
        else:
            info = _download_with_module(url, out_dir, progress, cookies_browser)
    except Exception as exc:
        msg = str(exc)
        msg = re.sub(r"\x1b\[[0-9;]*m", "", msg).replace("ERROR: ", "")
        hint = ""
        if "403" in msg or "Sign in" in msg or "bot" in msg:
            hint = ("\n\nYouTube refused the download. Try 'Update downloader' in Settings, "
                    "or enable 'Use browser cookies'.")
        raise RuntimeError(f"Download failed: {msg}{hint}") from exc

    audio_files = [p for p in out_dir.glob("source.*")
                   if p.suffix.lower() not in (".webp", ".jpg", ".jpeg", ".png", ".part", ".ytdl")]
    if not audio_files:
        raise RuntimeError("Download finished but no audio file was produced.")
    thumbs = [p for p in out_dir.glob("source.*") if p.suffix.lower() in (".webp", ".jpg", ".jpeg", ".png")]
    artist, title = guess_artist_title(info)
    year = ""
    if info.get("release_year"):
        year = str(info["release_year"])
    elif info.get("upload_date"):
        year = str(info["upload_date"])[:4]
    return SongInfo(
        audio_path=audio_files[0],
        title=title,
        artist=artist,
        album=info.get("album") or "",
        year=year,
        genre=(info.get("genre") or ""),
        thumbnail_path=thumbs[0] if thumbs else None,
        source_url=info.get("webpage_url") or url,
        extra={"duration": info.get("duration")},
    )


def fetch_metadata(url: str) -> dict:
    """Quick metadata lookup (no download) used to pre-fill the title/artist fields."""
    exe = _updated_ytdlp_exe()
    if exe:
        cmd = [str(exe), "--no-playlist", "--no-warnings", "-J", url]
        deno = paths.find_tool("deno")
        if deno:
            cmd[1:1] = ["--js-runtimes", f"deno:{deno}"]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              creationflags=_creationflags())
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "lookup failed")
        info = json.loads(proc.stdout)
    else:
        import yt_dlp

        opts = _common_opts(Path("."))
        opts.update({"skip_download": True, "writethumbnail": False})
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    artist, title = guess_artist_title(info)
    return {"artist": artist, "title": title, "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail")}


def read_tags(path: Path) -> dict[str, str]:
    """Read title/artist/... tags with ffmpeg's ffmetadata muxer."""
    ffmpeg = paths.find_tool("ffmpeg")
    if not ffmpeg:
        return {}
    proc = subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-i", str(path), "-f", "ffmetadata", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=_creationflags(),
    )
    tags: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if "=" in line and not line.startswith((";", "[")):
            k, v = line.split("=", 1)
            tags.setdefault(k.strip().lower(), v.strip())
    return tags


def local_song(path: Path) -> SongInfo:
    """Build SongInfo for a local file from its tags (or its file name)."""
    title = path.stem
    artist = "Unknown Artist"
    if " - " in title:
        artist, title = (s.strip() for s in title.split(" - ", 1))
    tags = read_tags(path)
    return SongInfo(
        audio_path=path,
        title=tags.get("title") or title,
        artist=tags.get("artist") or tags.get("album_artist") or artist,
        album=tags.get("album", ""),
        year=(tags.get("date") or tags.get("year") or "")[:4],
        genre=tags.get("genre", ""),
    )
