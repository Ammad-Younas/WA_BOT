"""Runtime binary manager: download + self-update of yt-dlp / ffmpeg / ffprobe / ffplay.

Nothing is shipped with the repo. On the first launch this module fetches the
right toolchain for the host OS straight from the upstream projects' *direct*
URLs (no third-party package managers):

    yt-dlp   https://github.com/yt-dlp/yt-dlp/releases/latest/download/<asset>
    ffmpeg   https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/...  (Windows)
             https://johnvansickle.com/ffmpeg/releases/...                      (Linux)
             https://evermeet.cx/ffmpeg/getrelease/...                          (macOS)

A background thread re-checks upstream "latest" URLs periodically and swaps in
a newer build when the redirect target (version tag in the URL) or the content
fingerprint changes. Disable entirely with env MADI_NO_BOOTSTRAP=1.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Optional

import requests

from config.configure_bot import (BIN_DIR, BIN_UPDATE_FIRST_DELAY_MINUTES,
                                  BIN_UPDATE_INTERVAL_HOURS, BINARIES_STATE,
                                  DENO, FFMPEG, FFMPEG_DIR, FFPROBE, FFPLAY,
                                  YTDLP)

_PLATFORM = platform.system().lower()  # "windows" | "darwin" | "linux"
_SPECS: Optional[list] = None
_SPECS_LOCK = threading.Lock()

_LOG = sys.stderr.write


def log(msg: str) -> None:
    _LOG(f"[{time.strftime('%H:%M:%S')}] [boot] {msg}\n")


# ---------------------------------------------------------------------------
# platform-scoped direct sources

def _specs() -> list[dict]:
    """List of download groups for the host OS."""
    global _SPECS
    with _SPECS_LOCK:
        if _SPECS is not None:
            return _SPECS

    ytdlp_asset = {
        "windows": "yt-dlp.exe",
        "linux": "yt-dlp_linux",
        "darwin": "yt-dlp_macos",
    }[_PLATFORM]

    groups: list[dict] = [{
        "id": "ytdlp",
        "url": f"https://github.com/yt-dlp/yt-dlp/releases/latest/download/{ytdlp_asset}",
        "fmt": "file",
        "tools": [{"key": "ytdlp", "local": YTDLP}],
    }]

    _deno_arch = "aarch64" if platform.machine().lower() in ("aarch64", "arm64") else "x86_64"
    deno_asset = {
        "windows": f"deno-{_deno_arch}-pc-windows-msvc.zip",
        "linux": f"deno-{_deno_arch}-unknown-linux-gnu.zip",
        "darwin": f"deno-{_deno_arch}-apple-darwin.zip",
    }[_PLATFORM]
    groups.append({
        "id": "deno",
        "url": f"https://github.com/denoland/deno/releases/latest/download/{deno_asset}",
        "fmt": "zip",
        "tools": [{"key": "deno", "local": DENO}],
    })

    if _PLATFORM == "windows":
        groups.append({
            "id": "ffmpeg",
            "url": ("https://github.com/BtbN/FFmpeg-Builds/releases/latest/"
                    "download/ffmpeg-master-latest-win64-gpl.zip"),
            "fmt": "zip",
            "tools": [
                {"key": "ffmpeg", "local": FFMPEG},
                {"key": "ffprobe", "local": FFPROBE},
                {"key": "ffplay", "local": FFPLAY, "optional": True},
            ],
        })
    elif _PLATFORM == "linux":
        arch = "arm64" if platform.machine().lower() in ("aarch64", "arm64") else "amd64"
        groups.append({
            "id": "ffmpeg",
            "url": (f"https://johnvansickle.com/ffmpeg/releases/"
                    f"ffmpeg-release-{arch}-static.tar.xz"),
            "fmt": "tarxz",
            "tools": [
                {"key": "ffmpeg", "local": FFMPEG},
                {"key": "ffprobe", "local": FFPROBE},
                {"key": "ffplay", "local": FFPLAY, "optional": True},
            ],
        })
    elif _PLATFORM == "darwin":
        # evermeet.cx publishes ffmpeg + ffprobe zips (no ffplay build).
        groups.append({
            "id": "ffmpeg",
            "url": "https://evermeet.cx/ffmpeg/getrelease/zip",
            "fmt": "zip",
            "tools": [{"key": "ffmpeg", "local": FFMPEG}],
        })
        groups.append({
            "id": "ffprobe",
            "url": "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip",
            "fmt": "zip",
            "tools": [{"key": "ffprobe", "local": FFPROBE}],
        })
        if not FFPLAY.exists():
            log("ffplay: no official macOS build exists (skipped)")

    _SPECS = groups
    return groups


# ---------------------------------------------------------------------------
# state (last-seen remote fingerprint per group id)

def _load_state() -> dict:
    try:
        if BINARIES_STATE.exists():
            return json.loads(BINARIES_STATE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        pass
    return {}


def _save_state(state: dict) -> None:
    try:
        BINARIES_STATE.parent.mkdir(parents=True, exist_ok=True)
        BINARIES_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# network helpers

def _probe(url: str) -> Optional[str]:
    """Lightweight remote fingerprint: final URL + size + last-modified.

    GitHub redirects `latest` downloads to a signed blob URL whose query
    string (signature/expiry) changes on every request, so the query is
    stripped — the asset path, size and mtime are what identify a build.
    """
    try:
        r = requests.head(url, allow_redirects=True, timeout=30)
        fp = r.url.split("?", 1)[0]
        size = r.headers.get("Content-Length")
        mod = r.headers.get("Last-Modified")
        if size:
            fp += f"|{size}"
        if mod:
            fp += f"|{mod}"
        return fp
    except requests.RequestException:
        return None


def _fetch(url: str, dest: Path) -> None:
    """Stream-download url directly to dest via a temp file, then atomic swap."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".dltmp")
    try:
        with requests.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    fh.write(chunk)
            if total and tmp.stat().st_size != total:
                raise RuntimeError(f"size mismatch (expected {total}, got {tmp.stat().st_size})")
        _safe_replace(tmp, dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _safe_replace(src: Path, dst: Path, tries: int = 3) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(tries):
        try:
            os.replace(src, dst)
            return
        except OSError:
            if attempt == tries - 1:
                raise
            time.sleep(1)  # target may be briefly held by an active ffmpeg subprocess


# ---------------------------------------------------------------------------
# install / extract

def _install_file(tool: dict, src: Path) -> None:
    _safe_replace(src, tool["local"])
    if _PLATFORM in ("linux", "darwin"):
        os.chmod(tool["local"], 0o755)


def _install_archive(group: dict, archive: Path) -> None:
    """Pull the needed members out of a zip/tar.xz and swap them in atomically.

    Optional tools (e.g. ffplay on Linux/macOS) are skipped when the build
    does not ship them; a missing required tool still aborts the install.
    """
    staging = Path(tempfile.mkdtemp(prefix="bininst_", dir=str(BIN_DIR)))
    committed = []
    try:
        for tool in group["tools"]:
            want = tool["local"].name  # e.g. ffmpeg / ffmpeg.exe
            member = _find_member(group["fmt"], archive, want)
            if member is None:
                if tool.get("optional"):
                    log(f"{want} not shipped in this build — skipping")
                    continue
                raise RuntimeError(f"{want} not found inside {archive.name}")
            target = staging / want
            _extract_member(group["fmt"], archive, member, target)
            if _PLATFORM in ("linux", "darwin"):
                os.chmod(target, 0o755)
            committed.append(tool)
        # commit only after every member extracted successfully
        for tool in committed:
            _safe_replace(staging / tool["local"].name, tool["local"])
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _find_member(fmt: str, archive: Path, name: str) -> Optional[str]:
    if fmt == "zip":
        with zipfile.ZipFile(archive) as z:
            for n in z.namelist():
                if Path(n).name == name:
                    return n
    else:  # tarxz
        with tarfile.open(archive, "r:xz") as t:
            for n in t.getnames():
                if Path(n).name == name:
                    return n
    return None


def _extract_member(fmt: str, archive: Path, member: str, target: Path) -> None:
    if fmt == "zip":
        with zipfile.ZipFile(archive) as z:
            with z.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    else:
        with tarfile.open(archive, "r:xz") as t:
            src = t.extractfile(member)
            if src is None:
                raise RuntimeError("empty archive member")
            with open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


# ---------------------------------------------------------------------------
# version detection (for logs)

def _tool_version(local: Path) -> str:
    try:
        proc = subprocess.run([str(local), "--version"], capture_output=True,
                              text=True, timeout=15)
        first = (proc.stdout or proc.stderr).splitlines()[0].strip()
        return first[:80]
    except Exception:
        return "?"


def _group_install(group: dict) -> str:
    """Download + install one group from its direct URL; returns remote fingerprint."""
    url = group["url"]
    fp = _probe(url)
    if fp is None:
        raise RuntimeError(f"could not reach {url}")

    ext = ".zip" if group["fmt"] == "zip" else (".tar.xz" if group["fmt"] == "tarxz" else ".bin")
    tmpdir = Path(tempfile.mkdtemp(prefix="bindl_", dir=str(BIN_DIR)))
    try:
        archive = tmpdir / f"{group['id']}{ext}"
        _fetch(url, archive)
        if group["fmt"] == "file":
            for tool in group["tools"]:
                _install_file(tool, archive)
        else:
            _install_archive(group, archive)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return fp


# ---------------------------------------------------------------------------
# public API

def ensure_binaries() -> None:
    """Fetch any missing tool for this OS (called once on startup)."""
    if os.environ.get("MADI_NO_BOOTSTRAP"):
        return
    groups = _specs()
    for group in groups:
        missing = [t for t in group["tools"] if not t.get("optional") and
                   (not t["local"].exists() or t["local"].stat().st_size == 0)]
        if not missing:
            continue
        for t in missing:
            log(f"downloading {t['key']} for {_PLATFORM}…")
        try:
            fp = _group_install(group)
        except Exception as e:
            log(f"{group['id']} download failed: {e}")
            continue
        for t in group["tools"]:
            if t["local"].exists():
                log(f"{t['key']} ready — {_tool_version(t['local'])}")
        _mark_state(group["id"], fp)


def check_updates() -> list[str]:
    """Compare remote fingerprints with the installed builds; update if changed.

    Returns human-readable log lines describing what happened.
    """
    if os.environ.get("MADI_NO_BOOTSTRAP"):
        return []
    changes: list[str] = []
    state = _load_state()
    for group in _specs():
        try:
            fp = _probe(group["url"])
        except Exception:
            fp = None
        if fp is None:
            changes.append(f"{group['id']}: upstream unreachable, skipped")
            continue
        if state.get("fingerprints", {}).get(group["id"]) == fp:
            continue
        changes.append(f"updating {group['id']} (new build detected)…")
        try:
            fp = _group_install(group)
            _mark_state(group["id"], fp)
            for t in group["tools"]:
                if t["local"].exists():
                    changes.append(f"{t['key']} updated — {_tool_version(t['local'])}")
        except Exception as e:
            changes.append(f"{group['id']} update failed: {e}")
    return changes


def _mark_state(group_id: str, fingerprint: str) -> None:
    state = _load_state()
    state.setdefault("fingerprints", {})[group_id] = fingerprint
    state["last_checked"] = time.time()
    _save_state(state)


# ---------------------------------------------------------------------------
# background updater thread

_updater_started = False


def start_updater() -> None:
    """Start the background updater thread (idempotent)."""
    global _updater_started
    if _updater_started or os.environ.get("MADI_NO_BOOTSTRAP"):
        return
    _updater_started = True
    threading.Thread(target=_updater_loop, name="bin-updater",
                     daemon=True).start()


def _updater_loop() -> None:
    interval = BIN_UPDATE_INTERVAL_HOURS * 3600
    first_delay = BIN_UPDATE_FIRST_DELAY_MINUTES * 60
    time.sleep(first_delay)
    while True:
        try:
            for line in check_updates():
                log(line)
        except Exception as e:
            log(f"updater error: {e}")
        time.sleep(interval)