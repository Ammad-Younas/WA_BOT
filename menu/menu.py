"""Menu texts and the command registry.

The WhatsApp UI renders *bold*, _italic_, ```code``` and =quotations=. Keep every
menu comfortably under the 4096-character message cap.
"""
from __future__ import annotations

from typing import Optional

from config.configure_bot import BOT_NAME, BOT_VER

def _header(title: str) -> str:
    return f"{title}\n{'=' * 22}"


def main_menu(profile_name: Optional[str] = None) -> str:
    greet = f"Hey *{profile_name}*" if profile_name else "Hey there 👋"
    body = f"""{greet}
Welcome to *{BOT_NAME}*.

*1.* About / Status
*2.* Download Video  (YouTube, TikTok, Insta…)
*3.* Download Audio MP3
*4.* Text Tools
*5.* Calculator
*6.* Random & Fun
*7.* Date & Time
*8.* Weather <city>
*9.* Dictionary <word>
*10.* Motivation Quote
*11.* Jokes & Facts
*12.* Notes / TODO
*13.* Reminders
*14.* Image Tools (QR, sticker…)
*15.* Convert Media
*16.* Media Info
*17.* YouTube Search

Type the number, or just type a keyword like `weather lahore`.
Reply *menu* anytime to see this again."""
    return _header(f"*{BOT_NAME}*") + "\n" + body


def text_tools_menu() -> str:
    body = """*Text Tools* — transform, encode, hash, and format text.

• `upper <text>`
• `lower <text>`
• `title <text>`
• `reverse <text>`
• `count <text>` (words & chars)
• `b64 <text>` (encode) · `unb64 <text>` (decode)
• `md5 <text>` · `sha1 <text>` · `sha256 <text>`
• `url <text>` (encode) · `unurl <text>` (decode)
• `json:<text>` (pretty-print JSON)
• `password <len=16>`
• `uuid`
• `alias <name>=<value>`

Type any, e.g. `b64 hello`"""
    return _header("Text Tools") + "\n" + body


def random_fun_menu() -> str:
    body = """*Random & Fun*

• `random <min> <max>`
• `dice`
• `coin`
• `choice a, b, c`
• `ask <question>` (Magic 8-ball)
• `even <n>` / `odd <n>`
• `prime <n>`
• `quote`
• `joke`
• `fact`

Try one: `ask is today my lucky day?`"""
    return _header("Random & Fun") + "\n" + body


def time_menu() -> str:
    body = """*Date & Time*

• `time`
• `now <city>`  (karachi, istanbul, london, delhi, dubai, any…)
• `unix <timestamp>`
• `days <YYYY-MM-DD> <YYYY-MM-DD>`
• `countdown <unix>`

Example: `now istanbul`"""
    return _header("Date & Time") + "\n" + body


def image_menu() -> str:
    body = """*Image Tools*

• `qr <text>` — generate a QR code image
• `sticker` — reply flow: command, then send an image → get a 512×512 WhatsApp sticker
• `info` — then send any image/video/audio for technical details

Type `qr` https://example.com to try it."""
    return _header("Image Tools") + "\n" + body


def media_menu() -> str:
    body = """*Download & Convert*

• `dl <video URL>` — video (mp4)
• `mp3 <video/audio URL>` — audio track (mp3)
• `yt <query>` — search YouTube (top 5, most viewed)
• `convert` — then send an audio/video file → get MP3
• `sticker` — turn an image into a WhatsApp sticker
• `info` — technical info of any media you send

Supported: YouTube, TikTok, Instagram, Facebook, Twitter/X, Reddit, Vimeo and most sites yt-dlp knows.

*Note:* results must stay under WhatsApp's 16 MB limit."""
    return _header("Media Center") + "\n" + body


def reminders_menu() -> str:
    body = """*Reminders*

• `remind in <minutes> <text>`
• `remind at <HH:MM> <text>`
• `reminders` — list active
• `cancel reminder <n>`
• `clear reminders`

Example: `remind in 10 take break`"""
    return _header("Reminders") + "\n" + body


def notes_menu() -> str:
    body = """*Notes / TODO*

• `note add <text>` — add a note
• `notes` — list all
• `note <n>` — view one
• `note del <n>` — delete one
• `note clear` — wipe all

Your notes are stored privately per conversation."""
    return _header("Notes") + "\n" + body


# --------------------------------------------------------------------------
# command → intent mapping
# --------------------------------------------------------------------------

# keywords are checked lowercase on the first word of the message
KEYWORD_MAP = {
    "menu": "menu", "help": "menu", "start": "menu", "hi": "menu",
    "hello": "menu", "assalam": "menu",
    "about": "about", "status": "about",
    "dl": "download", "download": "download", "video": "download",
    "mp3": "ytmp3", "audio": "ytmp3",
    "convert": "convert",
    "sticker": "sticker",
    "info": "media_info",
    "text": "text_menu", "tools": "text_menu", "texttools": "text_menu",
    "calc": "calc", "math": "calc", "calculate": "calc",
    "random": "random", "roll": "dice", "dice": "dice", "coin": "coin", "flip": "coin",
    "choice": "choice", "pick": "choice",
    "ask": "ask",
    "time": "time", "clock": "time",
    "now": "city_time",
    "unix": "unix",
    "days": "days",
    "countdown": "countdown",
    "weather": "weather", "wttr": "weather",
    "dict": "dictionary", "dictionary": "dictionary", "define": "dictionary",
    "quote": "quote", "motivate": "quote",
    "joke": "joke", "jokes": "joke",
    "fact": "fact", "facts": "fact",
    "note": "note", "notes": "notes", "todo": "notes", "remind": "remind",
    "reminder": "reminders", "reminders": "reminders",
    "qr": "qr", "qrcode": "qr",
    "upper": "upper", "lower": "lower", "title": "title",
    "reverse": "reverse", "rev": "reverse",
    "count": "count",
    "b64": "b64", "base64": "b64", "encode64": "b64",
    "unb64": "unb64", "decode64": "unb64", "d64": "unb64",
    "md5": "md5", "sha1": "sha1", "sha256": "sha256", "hash": "hash",
    "url": "urlencode", "encodeurl": "urlencode",
    "unurl": "urldecode", "decode": "urldecode",
    "password": "password", "pass": "password",
    "uuid": "uuid",
    "even": "even", "odd": "odd", "prime": "prime",
    "cancel": "cancel_reminder",
    "clear": "clear_reminders",
    "ping": "ping", "echo": "ping",
    "yt": "ytsearch", "yts": "ytsearch",
}

MAIN_NUMBERS = {
    "1": "about",
    "2": "download_menu",
    "3": "ytmp3_menu",
    "4": "text_menu",
    "5": "calc",
    "6": "random_menu",
    "7": "time_menu",
    "8": "weather",
    "9": "dictionary",
    "10": "quote",
    "11": "fun_menu",
    "12": "notes_menu",
    "13": "reminders_menu",
    "14": "image_menu",
    "15": "media_menu",
    "16": "media_info",
    "17": "ytsearch",
    "0": "menu",
}


def resolve_intent(first_word: str) -> Optional[str]:
    """Map a user's first word (lowercased, stripped) to an intent."""
    key = first_word.lower().strip(".,!?@")
    if key in KEYWORD_MAP:
        return KEYWORD_MAP[key]
    if key.isdigit() and key in MAIN_NUMBERS:
        return MAIN_NUMBERS[key]
    if key == "json" or key.startswith("json:"):
        return "json"
    if key.startswith("remind"):
        return "remind"
    return None


def about_text() -> str:
    return f"""*About {BOT_NAME} (v{BOT_VER})*

*Media downloads* (YouTube / TikTok / Instagram / more)
Audio extraction & MP3 conversion
Sticker maker, QR generator, media info
Calculator & math engine
*Text tools* (base64, hashes, case, JSON…)
Weather · Dictionary
Notes/TODO · Reminders
Random, fun, quotes & facts

Message cap: 4096 chars · Media cap: 16 MB (image 5 MB)

Type `menu` to see everything."""


def welcome_text(profile_name: Optional[str] = None) -> str:
    return main_menu(profile_name)


def ping_text() -> str:
    import time
    return f"pong ({time.strftime('%H:%M:%S')})"