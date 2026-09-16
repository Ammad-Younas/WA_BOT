"""Central configuration for the WhatsApp Agent Platform bot.

Loads secrets from the project .env file, defines API constants and paths to
the runtime-managed binaries (downloaded on first run and kept up to date by
utilities.bootstrap — nothing is shipped with the repo).
"""
import os
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

def _load_env() -> None:
    """Minimal .env loader (KEY=VALUE per line, supports quotes and # comments)."""
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and os.environ.get(key) is None:
            os.environ[key] = value

_load_env()

AGENT_API_KEY: str = os.environ.get("AGENT_API_KEY", "")
BASE_URL: str = "https://api.whatsapp.com/agent/v1"

AUTH_HEADERS: dict = {"Authorization": f"Bearer {AGENT_API_KEY}"}

BIN_DIR: Path = BASE_DIR / "binaries"
FFMPEG_DIR: Path = BIN_DIR / "ffmpeg_and_ffprobe"


def _tool(name: str) -> Path:
    """Binary path for the host OS (ffmpeg/ffprobe/ytdlp carry no .exe on POSIX)."""
    exe = name + (".exe" if os.name == "nt" else "")
    return (FFMPEG_DIR if name in ("ffmpeg", "ffprobe", "ffplay") else BIN_DIR / "ytdlp") / exe


FFMPEG: Path = _tool("ffmpeg")
FFPROBE: Path = _tool("ffprobe")
FFPLAY: Path = _tool("ffplay")
YTDLP: Path = _tool("ytdlp")
BINARIES_STATE: Path = BIN_DIR / "state.json"

# Deno JS runtime — required by modern yt-dlp to solve YouTube's JS challenges
# (signature/n challenge). Auto-downloaded by utilities.bootstrap.
DENO: Path = BIN_DIR / "deno" / ("deno.exe" if os.name == "nt" else "deno")

# Optional YouTube cookies file (exported from a browser) for stubborn bot checks.
# Point at it with the MADI_YOUTUBE_COOKIES env var (relative to the repo root).
_cookies_env = os.environ.get("MADI_YOUTUBE_COOKIES", "").strip()
if _cookies_env:
    YOUTUBE_COOKIES: Optional[Path] = (BASE_DIR / _cookies_env).resolve()
else:
    _default_cookies = BASE_DIR / "data" / "cookies" / "cookies.txt"
    YOUTUBE_COOKIES: Optional[Path] = _default_cookies if _default_cookies.exists() else None

# Background binary updater (see utilities.bootstrap)
BIN_UPDATE_INTERVAL_HOURS = int(os.environ.get("MADI_BIN_UPDATE_HOURS", "24"))
BIN_UPDATE_FIRST_DELAY_MINUTES = int(os.environ.get("MADI_BIN_UPDATE_FIRST_MIN", "5"))

DATA_DIR: Path = BASE_DIR / "data"
TMP_DIR: Path = DATA_DIR / "tmp"
DOWNLOADS_DIR: Path = DATA_DIR / "downloads"
for _d in (DATA_DIR, TMP_DIR, DOWNLOADS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

STATE_FILE: Path = DATA_DIR / "state.json"
NOTES_FILE: Path = DATA_DIR / "notes.json"
REMINDERS_FILE: Path = DATA_DIR / "reminders.json"
PROFILES_FILE: Path = DATA_DIR / "profiles.json"

BOT_NAME: str = "MADI BOT"
BOT_VER: str = "1.0.0"

# WhatsApp Agent Platform constraints
TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024
MAX_IMAGE = 5 * 1024 * 1024
MAX_STICKER = 500 * 1024
MAX_MEDIA = 16 * 1024 * 1024

POLL_BACKOFF_TIMEOUT = 20
PROCESS_TIMEOUT = 150