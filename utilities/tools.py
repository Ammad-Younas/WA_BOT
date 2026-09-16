"""General-purpose tools: text, math, random, time, weather, dictionary,
quotes, fun, notes, QR. Each function returns a BotResponse-like dict or a
string; handlers decide how to send it.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import math
import re
import secrets
import string
import time
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import requests

from config.configure_bot import NOTES_FILE, PROFILES_FILE, TMP_DIR

# --------------------------------------------------------------------------
# response helpers


def ok(text: str) -> dict:
    return {"text": text}


def media_result(path: str, media_type: str, caption: Optional[str] = None,
                 filename: Optional[str] = None) -> dict:
    return {"media_path": path, "media_type": media_type,
            "caption": caption, "filename": filename}


# --------------------------------------------------------------------------
# state / storage helpers


def _json_rw(path: Path, default: Any) -> Any:
    def load():
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                return default()
        return default()

    def dump(data: Any):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return load, dump


def make_profiles_io():
    load, dump = _json_rw(PROFILES_FILE, dict)
    return load, dump


def make_notes_io():
    def load() -> dict:
        data = {}
        if NOTES_FILE.exists():
            try:
                data = json.loads(NOTES_FILE.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                data = {}
        return data

    def dump(data: dict):
        NOTES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return load, dump

# --------------------------------------------------------------------------
# text tools


def b64encode(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def b64decode(text: str) -> str:
    try:
        return base64.b64decode(text + "=" * (-len(text) % 4)
                                if len(text) % 4 else text).decode("utf-8")
    except Exception:
        raise ValueError("invalid base64 input")


def to_hash(text: str, algo: str = "sha256") -> str:
    try:
        h = hashlib.new(algo)
    except ValueError:
        raise ValueError(f"unsupported algorithm: {algo}")
    h.update(text.encode("utf-8"))
    return h.hexdigest()


def case_convert(text: str, mode: str = "upper") -> str:
    modes = {"upper": str.upper, "lower": str.lower, "title": str.title,
             "capitalize": str.capitalize, "swapcase": str.swapcase}
    fn = modes.get(mode)
    if not fn:
        raise ValueError(f"unknown mode: {mode}")
    return fn(text)


def reverse_text(text: str) -> str:
    return text[::-1]


def count_text(text: str) -> str:
    words = re.findall(r"\S+", text)
    chars = len(text)
    return f"Words: {len(words)}\nCharacters: {chars}"


def url_encode(text: str) -> str:
    return urllib.parse.quote(text)


def url_decode(text: str) -> str:
    return urllib.parse.unquote(text)


def json_pretty(text: str) -> str:
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except ValueError:
        raise ValueError("invalid JSON")


def html_escape(text: str) -> str:
    return html.escape(text)


def html_unescape(text: str) -> str:
    return html.unescape(text)


def generate_password(length: int = 16) -> str:
    length = max(6, min(64, int(length)))
    pool = string.ascii_letters + string.digits + "!@#$%^&*()_+-=?"
    return "".join(secrets.choice(pool) for _ in range(length))


def gen_uuid() -> str:
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# safe calculator
# --------------------------------------------------------------------------

_MATH_SAFE = {
    "abs": abs, "round": round, "min": min, "max": max,
    "sqrt": math.sqrt, "cbrt": lambda x: x ** (1 / 3),
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "log": math.log, "log10": math.log10, "log2": math.log2,
    "exp": math.exp, "floor": math.floor, "ceil": math.ceil,
    "factorial": math.factorial, "fabs": math.fabs, "hypot": math.hypot,
    "degrees": math.degrees, "radians": math.radians,
    "pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf,
    "gcd": math.gcd, "perm": math.perm, "comb": math.comb,
}
_ALLOWED_NAMES = {"__builtins__": {}, **{k: v for k, v in _MATH_SAFE.items()}}


def calculate(expr: str) -> str:
    expr = expr.replace("^", "**")
    import ast
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) or (
            isinstance(node, ast.Call) and not isinstance(node.func, ast.Name)
        ):
            raise ValueError("only simple math expressions are allowed")
    code = compile(tree, "<calc>", "eval")
    result = eval(code, _ALLOWED_NAMES, {})  # noqa: S307 - restricted whitelist
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return str(result)

# --------------------------------------------------------------------------
# random / fun


def random_number(lo: int = 1, hi: int = 100) -> str:
    lo, hi = int(lo), int(hi)
    if lo > hi:
        lo, hi = hi, lo
    return f"*{secrets.randbelow(hi - lo + 1) + lo}* (between {lo} and {hi})"


def roll_dice() -> str:
    return f"You rolled a *{secrets.randbelow(6) + 1}*"


def flip_coin() -> str:
    return "*Heads*" if secrets.randbelow(2) else "*Tails*"


def pick_choice(items) -> str:
    clean = [x.strip() for x in items if x.strip()]
    if not clean:
        raise ValueError("give me at least one option")
    return f"I pick: *{secrets.choice(clean)}*"


_OK = [
    "It is certain.", "It is decidedly so.", "Without a doubt.",
    "Yes, definitely.", "You may rely on it.", "As I see it, yes.",
    "Most likely.", "Outlook good.", "Yes.", "Signs point to yes.",
    "Reply hazy, try again.", "Ask again later.", "Better not tell you now.",
    "Cannot predict now.", "Concentrate and ask again.",
    "Don't count on it.", "My reply is no.", "My sources say no.",
    "Outlook not so good.", "Very doubtful.",
]


def magic_8ball(question: str) -> str:
    return f"*{question}*\n\n{secrets.choice(_OK)}"


def pid_even_odd(n) -> str:
    n = int(n)
    return f"{n} is *{'even' if n % 2 == 0 else 'odd'}*"


def pid_prime(n) -> str:
    n = int(n)
    if n < 2:
        return f"{n} is *not prime*"
    for d in range(2, int(n ** 0.5) + 1):
        if n % d == 0:
            return f"{n} is *not prime* (divisible by {d})"
    return f"{n} is *prime*"

# --------------------------------------------------------------------------
# date & time

_TZ_MAP = {
    "karachi": "Asia/Karachi", "islamabad": "Asia/Karachi", "pk": "Asia/Karachi",
    "istanbul": "Europe/Istanbul", "tr": "Europe/Istanbul",
    "london": "Europe/London", "uk": "Europe/London",
    "newyork": "America/New_York", "ny": "America/New_York",
    "dubai": "Asia/Dubai", "uae": "Asia/Dubai",
    "losangeles": "America/Los_Angeles", "la": "America/Los_Angeles",
    "tokyo": "Asia/Tokyo", "sydney": "Australia/Sydney",
    "delhi": "Asia/Kolkata", "mumbai": "Asia/Kolkata",
    "riyadh": "Asia/Riyadh", "cairo": "Africa/Cairo",
    "paris": "Europe/Paris", "berlin": "Europe/Berlin",
    "toronto": "America/Toronto", "moscow": "Europe/Moscow",
}


def time_now() -> str:
    now = datetime.now()
    return now.strftime(f"%A, %d %B %Y\n%H:%M:%S\n(UTC{_utc_offset(now)})")


def _utc_offset(dt: datetime) -> str:
    off = dt.astimezone().utcoffset() or timedelta(0)
    s = off.total_seconds()
    sign = "+" if s >= 0 else "-"
    s = abs(int(s))
    return f"{sign}{s // 3600:02d}:{(s % 3600) // 60:02d}"


def city_time(city: str) -> str:
    tz_name = _TZ_MAP.get(city.strip().lower().replace(" ", ""))
    if not tz_name:
        names = ", ".join(k.title() for k in dict.fromkeys(_TZ_MAP.keys()) if len(k) > 2)
        raise ValueError(f"unknown city. Try one of: {names}")
    now = datetime.now(ZoneInfo(tz_name))
    return (f"*{city.title()}* ({tz_name.split('/')[-1]})\n"
            f"{now.strftime('%A, %d %B %Y')}\n{now.strftime('%H:%M:%S')}")


def unix_stamp(t) -> str:
    try:
        t = int(float(t))
    except ValueError:
        raise ValueError("give me a unix timestamp (seconds)")
    if t > 10**12:  # ms -> s
        t //= 1000
    dt = datetime.fromtimestamp(t, tz=timezone.utc)
    days_ago = (datetime.now(timezone.utc) - dt).days
    return (f"Unix *{t}* =\n{dt.strftime('%A, %d %B %Y %H:%M:%S')} UTC\n"
            f"({days_ago} day(s) ago)")


def countdown(target: str) -> str:
    try:
        target = float(target)
        now = time.time()
        diff = target - now
        if diff < 0:
            return "That moment already passed"
        m, s = divmod(int(diff), 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        return f"*{d}d {h}h {m}m {s}s* remaining"
    except ValueError:
        raise ValueError("give me a future unix timestamp")


def calc_days(a: str, b: str) -> str:
    try:
        d1 = datetime.strptime(a, "%Y-%m-%d").date()
        d2 = datetime.strptime(b, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("use YYYY-MM-DD")
    diff = abs((d2 - d1).days)
    return f"From {d1} to {d2} = *{diff} day(s)*"

# --------------------------------------------------------------------------
# weather


def weather(city: str) -> str:
    q = urllib.parse.quote(city.strip())
    fmt = "%l: %c %t %w %h %P"
    try:
        r = requests.get(f"https://wttr.in/{q}",
                         params={"format": fmt, "m": ""}, timeout=15)
        r.raise_for_status()
        out = r.text.strip().split("\n")[0]
    except requests.RequestException:
        raise RuntimeError("weather service unreachable, try again later")
    if not out or "Unknown location" in out or out.startswith("Unknown"):
        raise ValueError(f"city '{city}' not found")
    return f"{out.strip()}\n\n(_metric: temp°C, wind km/h, humidity %, pressure hPa_)"

# --------------------------------------------------------------------------
# dictionary
# --------------------------------------------------------------------------


def dictionary(word: str) -> str:
    word = word.strip().lower()
    try:
        r = requests.get("https://api.datamuse.com/words",
                         params={"md": "dpr", "max": 4, "sp": word},
                         timeout=15)
        r.raise_for_status()
        rows = [x for x in r.json() if x.get("defs")]
    except requests.RequestException:
        raise RuntimeError("dictionary service unreachable, try again later")

    if not rows:
        # likely a typo — offer the closest matches
        try:
            sug = requests.get("https://api.datamuse.com/words",
                               params={"max": 5, "ml": word}, timeout=15).json()
            suggests = [f"· {s.get('word')}" for s in sug if s.get("word")][:5]
        except requests.RequestException:
            suggests = []
        hint = "\n".join(suggests) if suggests else "—"
        return f"No definition found for ‘{word}’.\n\nMaybe you meant:\n{hint}"

    best = rows[0]
    lines = [f"*{best.get('word')}*"]
    tags = best.get("tags", [])
    for tag in tags:
        if tag[0] in "nvagr" and ":" not in tag:
            pos = {"n": "noun", "v": "verb", "a": "adjective",
                   "adv": "adverb", "r": "adverb"}.get(tag, tag)
            lines.append(f"_{pos}_")
            break
    pron = next((t.split(":", 1)[1].strip() for t in tags if t.startswith("pron:")), None)
    if pron:
        lines.append(f"Pronunciation: /{pron}/")
    for i, d in enumerate(best["defs"], 1):
        pos, _, definition = d.partition("\t")
        lines.append(f"\n{i}. {definition}")
    return "\n".join(lines)

# --------------------------------------------------------------------------
# quotes / fun content (offline, reliable)

QUOTES = [
    "The secret of getting ahead is getting started. — Mark Twain",
    "It always seems impossible until it's done. — Nelson Mandela",
    "Don't watch the clock; do what it does. Keep going. — Sam Levenson",
    "The best time to plant a tree was 20 years ago. The second best time is now.",
    "Do what you can, with what you have, where you are. — Theodore Roosevelt",
    "Success is not final, failure is not fatal: it is the courage to continue that counts. — Winston Churchill",
    "Happiness is not something ready made. It comes from your own actions. — Dalai Lama",
    "You miss 100% of the shots you don't take. — Wayne Gretzky",
    "Everything you've ever wanted is on the other side of fear.",
    "The only way to do great work is to love what you do. — Steve Jobs",
    "Believe you can and you're halfway there. — Theodore Roosevelt",
    "Act as if what you do makes a difference. It does. — William James",
    "Little by little, one travels far. — J.R.R. Tolkien",
    "It does not matter how slowly you go as long as you do not stop. — Confucius",
    "Dream big and dare to fail. — Norman Vaughan",
    "Start where you are. Use what you have. Do what you can. — Arthur Ashe",
    "Whether you think you can or you think you can't, you're right. — Henry Ford",
    "The harder you work for something, the greater you'll feel when you achieve it.",
    "Don't be pushed around by the problems in your life. Be led by the dreams in your heart.",
    "If you are not willing to risk the unusual, you will have to settle for the ordinary. — Jim Rohn",
    "Push yourself, because no one else is going to do it for you.",
    "Success doesn't come from what you do occasionally, but from what you do consistently.",
    "Great things never come from comfort zones.",
    "Dream it. Wish it. Do it.",
    "Stay hungry, stay foolish. — Steve Jobs",
]


def quote() -> str:
    return f"*Daily Motivation*\n\n“{secrets.choice(QUOTES)}”\n\nType `quote` again for another."


JOKES = [
    "Why don't skeletons fight each other? They don't have the guts.",
    "I told my computer I needed a break, and it said 'no problem — take a byte'.",
    "Why did the scarecrow win an award? He was outstanding in his field.",
    "What do you call a fake noodle? An impasta.",
    "Why did the bicycle fall over? Because it was two-tired.",
    "How does a penguin build its house? Igloos it together.",
    "I'm reading a book on anti-gravity. It's impossible to put down.",
    "What do you call cheese that isn't yours? Nacho cheese.",
    "Why don't eggs tell jokes? They'd crack each other up.",
    "I would avoid the sushi if I were you. It's a little fishy.",
    "What do you call a factory that makes okay products? A satisfactory.",
    "Why did the math book look sad? Because it had too many problems.",
    "What's orange and sounds like a parrot? A carrot.",
    "How do you make holy water? You boil the hell out of it.",
    "Why was the computer cold? It left its Windows open.",
    "What do you call a bear with no teeth? A gummy bear.",
    "Why did the golfer bring two pairs of pants? In case he got a hole in one.",
    "I only know 25 letters of the alphabet. I don't know y.",
    "When life gives you melons, you might be dyslexic.",
    "What's the best thing about Switzerland? I don't know, but the flag is a big plus.",
]


def joke() -> str:
    return f"*Joke time*\n\n{secrets.choice(JOKES)}"


FACTS = [
    "Honey never spoils. Archaeologists have found 3000-year-old honey in Egyptian tombs, still edible.",
    "Octopuses have three hearts and blue blood.",
    "A day on Venus is longer than a year on Venus.",
    "Bananas are berries, but strawberries aren't.",
    "The shortest war in history lasted only 38 minutes (Zanzibar vs Britain, 1896).",
    "Your brain uses about 20% of your body's total energy.",
    "There are more possible chess games than there are atoms in the observable universe.",
    "The Eiffel Tower can be 15 cm taller in summer due to thermal expansion.",
    "Cows have best friends and get stressed when separated from them.",
    "A group of flamingos is called a 'flamboyance'.",
    "Honeybees can recognize human faces.",
    "The Pacific Ocean is wider than the Moon.",
    "Sharks existed before trees.",
    "Wombat poop is cube-shaped.",
    "The human body has about 60,000 miles of blood vessels.",
    "Camel milk doesn't curdle, while cow milk does.",
    "The first webcam in history was used to watch a coffee pot.",
    "There are more trees on Earth than stars in the Milky Way.",
    "A bolt of lightning is five times hotter than the sun's surface.",
    "The word 'selfie' dates back to 2002 — from an Australian forum.",
]


def fact() -> str:
    return f"*Random fact*\n\n{secrets.choice(FACTS)}"

# --------------------------------------------------------------------------
# notes / todo

NOTES_LOAD, NOTES_DUMP = make_notes_io()


def notes_list(user: str) -> str:
    data = NOTES_LOAD()
    items = data.get(user, [])
    if not items:
        return "You have *no notes* yet.\n\nAdd one with: `note add <text>`"
    lines = [f"*Your notes ({len(items)})*"]
    for i, note in enumerate(items, 1):
        lines.append(f"\n{i}. {note}")
    lines.append("\n\nGet one: `note <n>`  |  Delete: `note del <n>`  |  Clear: `note clear`")
    return "\n".join(lines)


def note_add(user: str, text: str) -> str:
    data = NOTES_LOAD()
    items = data.setdefault(user, [])
    items.append(text.strip())
    NOTES_DUMP(data)
    return f"Note added as *#{len(items)}*:\n\n{text.strip()}"


def note_get(user: str, n: int) -> str:
    items = NOTES_LOAD().get(user, [])
    try:
        note = items[n - 1]
    except IndexError:
        raise ValueError(f"you only have {len(items)} note(s)")
    return f"Note *#{n}*:\n\n{note}"


def note_del(user: str, n: int) -> str:
    data = NOTES_LOAD()
    items = data.get(user, [])
    try:
        removed = items.pop(n - 1)
    except IndexError:
        raise ValueError(f"you only have {len(items)} note(s)")
    NOTES_DUMP(data)
    return f"Deleted note #{n}:\n\n{removed}"


def note_clear(user: str) -> str:
    data = NOTES_LOAD()
    n = len(data.pop(user, []))
    NOTES_DUMP(data)
    return f"Cleared *{n}* note(s)"

# --------------------------------------------------------------------------
# QR code


def make_qr(text: str) -> str:
    import qrcode
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    path = TMP_DIR / f"qr_{int(time.time())}_{secrets.randbelow(9999)}.png"
    img.save(path)
    return str(path)


# --------------------------------------------------------------------------
# misc helpers

MIME_BY_EXT = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp",
    ".mp4": "video/mp4", ".3gp": "video/3gpp", ".mov": "video/quicktime",
    ".webm": "video/webm", ".m4v": "video/mp4",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
    ".ogg": "audio/ogg", ".opus": "audio/opus", ".wav": "audio/wav",
    ".amr": "audio/amr",
    ".pdf": "application/pdf", ".txt": "text/plain", ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".zip": "application/zip", ".bin": "application/octet-stream",
}


def mime_for(name: str) -> str:
    ext = Path(name).suffix.lower()
    return MIME_BY_EXT.get(ext, "application/octet-stream")


def human_size(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def is_url(text: str) -> bool:
    return bool(re.match(r"^https?://\S+", text.strip()))