"""Media pipelines powered by the runtime-managed yt-dlp and ffmpeg binaries
(fetched & kept up to date by utilities.bootstrap):
downloads, audio extraction, transcoding, stickers, and file probing.
"""
from __future__ import annotations

import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from config.configure_bot import DOWNLOADS_DIR, FFMPEG, FFMPEG_DIR, FFPROBE, TMP_DIR, YTDLP

CREATE_NO_WINDOW = 0x08000000
PROC_KW = {"creationflags": CREATE_NO_WINDOW} if __import__("os").name == "nt" else {}

MAX_FILESIZE = "15M"  # keep comfortably under the 16 MB WhatsApp limit


def _run(args: list, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True,
                          timeout=timeout, **PROC_KW)


def _err_tail(err: str) -> str:
    lines = [l for l in (err or "").splitlines() if l.strip()]
    return "\n".join(lines[-6:]) or "no details"


def _unique_stem(prefix: str) -> str:
    return f"{prefix}_{int(time.time())}_{secrets.randbelow(100000)}"


def _find_output(stem: str) -> Optional[Path]:
    matches = list(DOWNLOADS_DIR.glob(f"{stem}.*"))
    if not matches:
        return None
    out = max(matches, key=lambda p: p.stat().st_mtime)
    if out.suffix.lower() in {".part", ".ytdl", ".temp", ".webm"}:
        return None if out.suffix.lower() in {".part", ".ytdl", ".temp"} else out
    return out


# --------------------------------------------------------------------------
# yt-dlp downloads (YouTube, TikTok, Instagram, Facebook, Twitter, Reddit ...)
# --------------------------------------------------------------------------

def download_media_url(url: str, mode: str = "video") -> str:
    """Download a video/audio file from a supported URL.

    mode: "video" -> mp4 (h264+aac, re-encoded if necessary),
          "audio" -> mp3 (extracted with ffmpeg).
    Returns the local file path or raises RuntimeError/ValueError.
    """
    stem = _unique_stem("dl")
    out_tpl = str(DOWNLOADS_DIR / f"{stem}.%(ext)s")
    base = [
        str(YTDLP),
        "--no-playlist",
        "--no-write-info-json",
        "--no-write-thumbnail",
        "--max-filesize", MAX_FILESIZE,
        "--ffmpeg-location", str(FFMPEG_DIR),
    ]
    if mode == "audio":
        base += ["-x", "--audio-format", "mp3", "--audio-quality", "5",
                 "-o", out_tpl]
    else:
        # Prefer a small h264+AAC mp4 stream over the network (fast, direct),
        # fall back to a combined small mp4, then anything <=480p.
        base += [
            "-f",
            (""  # 1) separate h264 video + aac audio, both under the cap
             "bv*[height<=720][ext=mp4][vcodec^=avc1][filesize<15M]"
             "+ba[ext=m4a][filesize<15M]"
             "/"  # 2) combined h264 mp4
             "b[height<=720][ext=mp4][vcodec^=avc1][filesize<15M]"
             "/"  # 3) anything at a modest resolution
             "bv*[height<=480]+ba/b[height<=480]"),
            "--merge-output-format", "mp4",
            "-o", out_tpl,
        ]
    base.append(url)

    cmd = base
    for attempt in range(2):
        try:
            proc = _run(cmd)
        except subprocess.TimeoutExpired:
            raise RuntimeError("download timed out (file may be too big or the source is slow)")

        out = _find_output(stem)
        if proc.returncode == 0 and out is not None:
            if mode == "video":
                out = _normalize_to_mp4(out)
                if out.stat().st_size > 16 * 1024 * 1024:
                    out = _compress_media(out)
            elif out.stat().st_size > 16 * 1024 * 1024:
                raise RuntimeError("the audio file exceeds WhatsApp's 16 MB limit")
            return str(out)
        # YouTube's `web` client now needs a JS runtime and can 403 without one.
        # Fall back to the android/ios/tv clients (self-contained signatures).
        err = proc.stderr.decode("utf-8", "replace")
        if attempt == 0 and "youtube" in err and (
            "JavaScript runtime" in err or "403" in err
        ):
            cmd = base[:-1] + [
                "--extractor-args", "youtube:player_client=android,ios,tv",
                url,
            ]
            continue
        raise RuntimeError(
            "couldn't download that link.\n"
            + ("Reason: " + _err_tail(proc.stderr) if proc.stderr.strip() else "Check the URL.")
        )
    raise RuntimeError("couldn't download that link. Reason: unknown yt-dlp failure")


def _normalize_to_mp4(path: Path) -> Path:
    """Ensure the result is an mp4 with h264 video + AAC audio (WhatsApp-safe)."""
    if path.suffix.lower() == ".mp4":
        return path
    out = DOWNLOADS_DIR / f"{path.stem}.mp4"
    ffmpeg_cmd = [
        str(FFMPEG), "-y", "-i", str(path),
        "-c:v", "libx264", "-preset", "fast", "-crf", "26",
        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
        "-vf", "scale='min(720,iw)':-2",
        str(out),
    ]
    proc = _run(ffmpeg_cmd, timeout=300)
    path.unlink(missing_ok=True)
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError("couldn't convert the downloaded file to mp4")
    return out


def _compress_media(path: Path) -> Path:
    """Re-encode an over-limit file down to fit WhatsApp's 16 MB cap."""
    out = DOWNLOADS_DIR / f"{path.stem}_small.mp4"
    ffmpeg_cmd = [
        str(FFMPEG), "-y", "-i", str(path),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "32",
        "-vf", "scale=-2:360",
        "-c:a", "aac", "-b:a", "64k",
        "-movflags", "+faststart",
        str(out),
    ]
    proc = _run(ffmpeg_cmd, timeout=300)
    path.unlink(missing_ok=True)
    if proc.returncode != 0 or not out.exists() or out.stat().st_size > 16 * 1024 * 1024:
        raise RuntimeError("media exceeds WhatsApp's 16 MB limit and couldn't be compressed")
    return out


def youtube_search(query: str, limit: int = 10) -> list[dict]:
    """YouTube search via the flat playlist extractor.

    Fast and lightweight (no full video extraction). Results are sorted by
    view count descending so the most-viewed matches come first.
    Returns [{title, url, views}] or raises RuntimeError.
    """
    import json as _json

    q = query.strip()
    if not q:
        raise ValueError("query is empty")
    proc = _run([
        str(YTDLP), "--no-playlist", "--flat-playlist", "--no-warnings",
        "-J", f"ytsearch{limit}:{q}",
    ], timeout=150)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError("search failed: " + _err_tail(proc.stderr))

    try:
        data = _json.loads(proc.stdout)
    except ValueError as e:
        raise RuntimeError("search result couldn't be parsed") from e

    out = []
    for entry in data.get("entries", []):
        vid, title = entry.get("id"), (entry.get("title") or "").strip()
        if not vid or not title:
            continue
        views = entry.get("view_count") or 0
        out.append({"id": vid,
                    "title": title,
                    "url": f"https://youtu.be/{vid}",
                    "views": int(views)})
    out.sort(key=lambda r: r["views"], reverse=True)
    return out[:limit]


def fetch_thumbnail(video_id: str) -> Optional[str]:
    """Download the YouTube thumbnail for a video id -> local path (or None).

    Tries the max-quality image first, falling back to hq/mq defaults.
    """
    import requests as _requests

    if not video_id:
        return None
    for key in ("maxresdefault", "hqdefault", "mqdefault"):
        url = f"https://i.ytimg.com/vi/{video_id}/{key}.jpg"
        out = TMP_DIR / f"thumb_{_unique_stem('t')}_{key}.jpg"
        try:
            r = _requests.get(url, timeout=20)
            data = r.content if r.status_code == 200 else b""
        except _requests.RequestException:
            data = b""
        if len(data) > 1000 and data[:2] == b"\xff\xd8":  # real JPEG
            out.write_bytes(data)
            return str(out)
        out.unlink(missing_ok=True)
    return None


# --------------------------------------------------------------------------
# ffmpeg pipelines
# --------------------------------------------------------------------------

def image_to_sticker(src: str) -> str:
    """Resize/pad an image to a 512x512 WebP WhatsApp sticker."""
    from PIL import Image

    im = Image.open(src)
    im = im.convert("RGBA")
    im.thumbnail((512, 512))
    canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    canvas.paste(im, ((512 - im.width) // 2, (512 - im.height) // 2))
    out = TMP_DIR / f"sticker_{_unique_stem('st')}.webp"
    canvas.save(out, "WEBP", quality=90, method=6)
    return str(out)


def convert_to_mp3(src: str) -> str:
    out = TMP_DIR / f"conv_{_unique_stem('au')}.mp3"
    proc = _run([
        str(FFMPEG), "-y", "-i", src,
        "-vn", "-codec:a", "libmp3lame", "-b:a", "160k",
        str(out),
    ], timeout=180)
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError("audio conversion failed")
    if out.stat().st_size > 16 * 1024 * 1024:
        raise RuntimeError("converted audio exceeds WhatsApp's 16 MB limit")
    return str(out)


def probe_media(path: str) -> dict:
    """Return a small ffprobe summary dict for a media file."""
    out = TMP_DIR / f"probe_{_unique_stem('p')}.json"
    proc = _run([str(FFPROBE), "-v", "error", "-show_format", "-show_streams",
                 "-of", "json", path])
    out.unlink(missing_ok=True)
    if proc.returncode != 0:
        return {}
    import json
    try:
        return json.loads(proc.stdout or "{}")
    except ValueError:
        return {}


def media_summary(path: str) -> str:
    """Human-readable info card for a media file."""
    info = probe_media(path)
    stream = (info.get("streams") or [{}])[0]
    fmt = info.get("format") or {}
    size = int(fmt.get("size") or 0)
    dur = float(fmt.get("duration") or 0)
    lines = [
        "🎞️ *Media summary*",
        f"Size: {size / 1024:.1f} KB",
        f"Duration: {int(dur // 60)}m {int(dur % 60)}s",
    ]
    if stream.get("codec_name"):
        lines.append(f"Codec: {stream.get('codec_name')} ({stream.get('codec_type')})")
    w = stream.get("width")
    if w:
        lines.append(f"Resolution: {w}x{stream.get('height')}")
        lines.append(f"FPS: {stream.get('avg_frame_rate', '?')}")
    if stream.get("sample_rate"):
        lines.append(f"Sample rate: {stream.get('sample_rate')} Hz")
    return "\n".join(lines)


def cleanup_old_files(max_age_hours: int = 6) -> None:
    """Remove stale downloads/transcodes/data to keep the folder tidy."""
    cutoff = time.time() - max_age_hours * 3600
    for folder in (TMP_DIR, DOWNLOADS_DIR):
        for f in folder.iterdir():
            if f.is_file():
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink(missing_ok=True)
                except OSError:
                    pass