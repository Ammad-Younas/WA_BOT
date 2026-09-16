"""Message processing: intent routing, per-user state machine (multistep
flows), inbound media handling, notes/reminders glue and response shaping.
Every handler returns a dict:

    {"text": str}
    {"media_path": path, "media_type": <type>, "caption":?, "filename":? }

The sender thread in main.py turns these into API calls.
"""
from __future__ import annotations

import re
import secrets
import time
from pathlib import Path
from typing import Optional

from config.configure_bot import TMP_DIR
from menu import menu as menus
from utilities import api_client, media_tools, tools

# --------------------------------------------------------------------------
# per-user multi-step state

_STATES: dict[str, str] = {}
_STATE_LOCK = __import__("threading").Lock()

VALID_STATES = {"wait:download", "wait:mp3", "wait:convert",
                "wait:sticker", "wait:info", "wait:remind"}


def set_state(user: str, state: str) -> None:
    with _STATE_LOCK:
        _STATES[user] = state


def get_state(user: str) -> Optional[str]:
    with _STATE_LOCK:
        return _STATES.get(user)


def clear_state(user: str) -> None:
    with _STATE_LOCK:
        _STATES.pop(user, None)


# --------------------------------------------------------------------------
# profile memory (display names from GET /updates contacts)

PROFILES_LOAD, PROFILES_DUMP = tools.make_profiles_io()
_PROFILES = PROFILES_LOAD()


def remember_profile(wa_id: str, name: Optional[str]) -> None:
    if not name:
        return
    _PROFILES[wa_id] = name
    PROFILES_DUMP(_PROFILES)


def profile_name(wa_id: str) -> Optional[str]:
    name = _PROFILES.get(wa_id)
    if name:
        return name
    return None


def _short_id(user: str) -> str:
    return user.rsplit(":", 1)[-1][-6:]

# --------------------------------------------------------------------------
# text intent handlers


def _h_menu(user: str, args: str, msg: dict) -> dict:
    clear_state(user)
    return {"text": menus.main_menu(profile_name(user))}


def _h_about(user: str, args: str, msg: dict) -> dict:
    return {"text": menus.about_text()}


def _h_ping(user: str, args: str, msg: dict) -> dict:
    return {"text": menus.ping_text()}


def _h_text_menu(user: str, args: str, msg: dict) -> dict:
    return {"text": menus.text_tools_menu()}


def _h_random_menu(user: str, args: str, msg: dict) -> dict:
    return {"text": menus.random_fun_menu()}


def _h_time_menu(user: str, args: str, msg: dict) -> dict:
    return {"text": menus.time_menu()}


def _h_image_menu(user: str, args: str, msg: dict) -> dict:
    return {"text": menus.image_menu()}


def _h_media_menu(user: str, args: str, msg: dict) -> dict:
    return {"text": menus.media_menu()}


def _h_notes_menu(user: str, args: str, msg: dict) -> dict:
    return {"text": menus.notes_menu()}


def _h_reminders_menu(user: str, args: str, msg: dict) -> dict:
    return {"text": menus.reminders_menu()}


def _h_fun_menu(user: str, args: str, msg: dict) -> dict:
    return {"text": menus.random_fun_menu()}


def _h_download_menu(user: str, args: str, msg: dict) -> dict:
    return {"text": menus.media_menu()}


def _h_ytmp3_menu(user: str, args: str, msg: dict) -> dict:
    return {"text": menus.media_menu()}


def _h_calc(user: str, args: str, msg: dict) -> dict:
    if not args:
        return {"text": "Usage: `calc <expression>`\n\nExamples:\n`calc 2^10`\n`calc sqrt(144)+6`\n`calc sin(30)*cos(60)`\n\nSupports (+, -, *, /, %, **, //, parentheses, and math funcs.)"}
    expr = args.strip()
    result = tools.calculate(expr)
    return {"text": f"`{expr}`\n= *{result}*"}


def _h_upper(user: str, args: str, msg: dict) -> dict:
    return {"text": f"{tools.case_convert(args, 'upper')}"}


def _h_lower(user: str, args: str, msg: dict) -> dict:
    return {"text": f"{tools.case_convert(args, 'lower')}"}


def _h_title(user: str, args: str, msg: dict) -> dict:
    return {"text": f"{tools.case_convert(args, 'title')}"}


def _h_reverse(user: str, args: str, msg: dict) -> dict:
    out = tools.reverse_text(args)
    return {"text": f"Reversed:\n\n{out}"}


def _h_count(user: str, args: str, msg: dict) -> dict:
    return {"text": tools.count_text(args)}


def _h_b64(user: str, args: str, msg: dict) -> dict:
    return {"text": f"Base64:\n\n{tools.b64encode(args)}"}


def _h_unb64(user: str, args: str, msg: dict) -> dict:
    return {"text": f"Decoded:\n\n{tools.b64decode(args)}"}


def _h_md5(user: str, args: str, msg: dict) -> dict:
    return {"text": f"MD5: `{tools.to_hash(args, 'md5')}`"}


def _h_sha1(user: str, args: str, msg: dict) -> dict:
    return {"text": f"SHA1: `{tools.to_hash(args, 'sha1')}`"}


def _h_sha256(user: str, args: str, msg: dict) -> dict:
    return {"text": f"SHA256: `{tools.to_hash(args, 'sha256')}`"}


def _h_hash(user: str, args: str, msg: dict) -> dict:
    parts = args.split(None, 1)
    if len(parts) != 2:
        return {"text": "Usage: `hash <md5|sha1|sha256> <text>`"}
    algo, text = parts
    return {"text": f"{algo.upper()}: `{tools.to_hash(text, algo)}`"}


def _h_urlencode(user: str, args: str, msg: dict) -> dict:
    return {"text": f"Encoded:\n\n{tools.url_encode(args)}"}


def _h_urldecode(user: str, args: str, msg: dict) -> dict:
    return {"text": f"Decoded:\n\n{tools.url_decode(args)}"}


def _h_json(user: str, args: str, msg: dict) -> dict:
    return {"text": f"Pretty JSON:\n```\n{tools.json_pretty(args)}\n```"}


def _h_password(user: str, args: str, msg: dict) -> dict:
    n = int(args) if args.strip().isdigit() else 16
    return {"text": f"Password ({n} chars):\n\n`{tools.generate_password(n)}`"}


def _h_uuid(user: str, args: str, msg: dict) -> dict:
    return {"text": f"UUID: `{tools.gen_uuid()}`"}


def _h_random(user: str, args: str, msg: dict) -> dict:
    parts = args.split()
    if not parts:
        return {"text": "Usage: `random <min> <max>`  (e.g. `random 1 6`)"}
    lo = int(parts[0])
    hi = int(parts[1]) if len(parts) > 1 else 100
    return {"text": tools.random_number(lo, hi)}


def _h_dice(user: str, args: str, msg: dict) -> dict:
    return {"text": tools.roll_dice()}


def _h_coin(user: str, args: str, msg: dict) -> dict:
    return {"text": tools.flip_coin()}


def _h_choice(user: str, args: str, msg: dict) -> dict:
    items = [x for x in re.split(r"[,|\n]", args) if x.strip()]
    return {"text": tools.pick_choice(items)}


def _h_ask(user: str, args: str, msg: dict) -> dict:
    if not args:
        return {"text": "Ask me a yes/no question, e.g. `ask will it rain today?`"}
    return {"text": tools.magic_8ball(args)}


def _h_even(user: str, args: str, msg: dict) -> dict:
    return {"text": tools.pid_even_odd(args)}


def _h_odd(user: str, args: str, msg: dict) -> dict:
    if not args.strip().isdigit():
        return {"text": "Usage: `odd <n>`"}
    return {"text": tools.pid_even_odd(args)}


def _h_prime(user: str, args: str, msg: dict) -> dict:
    return {"text": tools.pid_prime(args)}


def _h_time(user: str, args: str, msg: dict) -> dict:
    return {"text": tools.time_now()}


def _h_city_time(user: str, args: str, msg: dict) -> dict:
    if not args:
        return {"text": menus.time_menu()}
    return {"text": tools.city_time(args)}


def _h_unix(user: str, args: str, msg: dict) -> dict:
    if not args:
        return {"text": "Usage: `unix <timestamp>`\n\nExample: `unix 1736844652`"}
    return {"text": tools.unix_stamp(args)}


def _h_days(user: str, args: str, msg: dict) -> dict:
    parts = args.split()
    if len(parts) != 2:
        return {"text": "Usage: `days <YYYY-MM-DD> <YYYY-MM-DD>`"}
    return {"text": tools.calc_days(parts[0], parts[1])}


def _h_countdown(user: str, args: str, msg: dict) -> dict:
    if not args:
        return {"text": "Usage: `countdown <unix timestamp>`"}
    return {"text": tools.countdown(args)}


def _h_weather(user: str, args: str, msg: dict) -> dict:
    if not args:
        return {"text": "Usage: `weather <city>`\n\nExamples:\n`weather lahore`\n`weather istanbul`\n`weather london`"}
    return {"text": tools.weather(args)}


def _h_dictionary(user: str, args: str, msg: dict) -> dict:
    if not args:
        return {"text": "Usage: `dict <word>`\n\nExample: `dict serendipity`"}
    return {"text": tools.dictionary(args)}


def _h_quote(user: str, args: str, msg: dict) -> dict:
    return {"text": tools.quote()}


def _h_joke(user: str, args: str, msg: dict) -> dict:
    return {"text": tools.joke()}


def _h_fact(user: str, args: str, msg: dict) -> dict:
    return {"text": tools.fact()}


def _h_qr(user: str, args: str, msg: dict) -> dict:
    if not args:
        return {"text": "Usage: `qr <text or link>`\n\nExample: `qr https://example.com`"}
    return tools.media_result(tools.make_qr(args), "image")


def _h_note(user: str, args: str, msg: dict) -> dict:
    low = args.lower()
    if args.startswith("add "):
        return {"text": tools.note_add(user, args[4:])}
    if low.startswith("del ") or low.startswith("delete "):
        n = args.split(None, 1)[-1]
        if not n.isdigit():
            raise ValueError("usage: `note del <n>`")
        return {"text": tools.note_del(user, int(n))}
    if low == "clear":
        return {"text": tools.note_clear(user)}
    if args.strip().isdigit():
        return {"text": tools.note_get(user, int(args.strip()))}
    if not args.strip():
        return {"text": tools.notes_list(user)}
    return {"text": tools.note_add(user, args)}


def _h_notes(user: str, args: str, msg: dict) -> dict:
    return {"text": tools.notes_list(user)}


def _h_remind(user: str, args: str, msg: dict) -> dict:
    if not args.strip():
        set_state(user, "wait:remind")
        return {"text": "Tell me when, in the form:\n`in <minutes> <text>`\n`at <HH:MM> <text>`\n\nExample: `in 20 call mom`"}
    from utilities import scheduler
    due, text = scheduler.parse_reminder(args)
    if due is None:
        return {"text": "Unclear. Use:\n`in <minutes> <text>`\n`at <HH:MM am/pm> <text>`"}
    idx = scheduler.add_reminder(user, due, text)
    when = time.strftime("%H:%M %d %b", time.localtime(due))
    return {"text": f"Reminder *#{idx}* set for _{when}_\n\n“{text}”"}


def _h_reminders(user: str, args: str, msg: dict) -> dict:
    from utilities import scheduler
    return {"text": scheduler.list_reminders(user)}


def _h_cancel_reminder(user: str, args: str, msg: dict) -> dict:
    from utilities import scheduler
    n = args.lower().replace("reminder", "").strip()
    if not n.isdigit():
        return {"text": scheduler.list_reminders(user)}
    return {"text": scheduler.remove_reminder(user, int(n))}


def _h_clear_reminders(user: str, args: str, msg: dict) -> dict:
    from utilities import scheduler
    return {"text": scheduler.clear_reminders(user)}


# --------------------------------------------------------------------------
# download / sticker / convert handlers (media output)

def _tmp_file(ext: str) -> str:
    return str(TMP_DIR / f"in_{int(time.time())}_{secrets.randbelow(100000)}.{ext}")


def _do_download(user: str, url: str, mode: str) -> dict:
    try:
        path = media_tools.download_media_url(url, mode)
    except (RuntimeError, ValueError) as e:
        return {"text": f"{e}"}
    except Exception as e:
        return {"text": f"Download failed ({type(e).__name__}): {e}"}
    mtype = "video" if mode == "video" else "audio"
    name = Path(path).name
    label = "Video" if mode == "video" else "MP3"
    return {"media_path": path, "media_type": mtype,
            "caption": f"{label} ready", "filename": name if mode == "audio" else None}


def _h_download(user: str, args: str, msg: dict) -> dict:
    if tools.is_url(args):
        return _do_download(user, args, "video")
    set_state(user, "wait:download")
    return {"text": "Send me the *link* and I'll download it as video (mp4)\n\n_(YouTube, TikTok, Instagram, Facebook, Twitter/X, Reddit…)_"}


def _h_ytmp3(user: str, args: str, msg: dict) -> dict:
    if tools.is_url(args):
        return _do_download(user, args, "audio")
    set_state(user, "wait:mp3")
    return {"text": "Send me the *link* and I'll turn it into MP3"}


def _h_sticker(user: str, args: str, msg: dict) -> dict:
    set_state(user, "wait:sticker")
    return {"text": "*Sticker mode* ON.\n\nSend me an *image* and I'll turn it into a 512×512 WhatsApp sticker."}


def _h_convert(user: str, args: str, msg: dict) -> dict:
    set_state(user, "wait:convert")
    return {"text": "*Convert mode* ON.\n\nSend me an *audio or video* file and I'll return it as MP3."}


def _h_media_info(user: str, args: str, msg: dict) -> dict:
    set_state(user, "wait:info")
    return {"text": "*Inspector* ON.\n\nSend any image / video / audio and I'll reply with its technical details."}


def _h_ytsearch(user: str, args: str, msg: dict) -> dict:
    q = args.strip()
    if not q:
        return {"text": "Usage: `yt <query>`\n\nExample: `yt top file life hacks`\n\nReturns the top 5 most-viewed matches."}
    try:
        results = media_tools.youtube_search(q, limit=5)
    except (RuntimeError, ValueError) as e:
        return {"text": f"{e}"}
    if not results:
        return {"text": f"No results found for '{q}'."}

    # build the result list (kept as the image caption, cap ~1000 chars)
    entries = []
    for i, r in enumerate(results, 1):
        views = f"{r['views']:,}" if r["views"] else "—"
        entries.append(f"\n*{i}.* {r['title']}\nLink. {r['url']}\nViews. {views}\n")
    caption = f"Here is top {len(results)} result of your *{q}*\n"
    overflow_lines: list = []
    for block in entries:
        if len(caption) + len(block) <= 1000:
            caption += block
        else:
            overflow_lines.append(block.strip())

    thumb = media_tools.fetch_thumbnail(results[0]["id"])
    if not thumb:
        # no thumbnail — send the plain list as text
        return {"text": caption + (("\n" + "\n\n".join(overflow_lines)) if overflow_lines else "")}

    resp = {"media_path": thumb, "media_type": "image",
            "caption": caption}
    if overflow_lines:
        resp["followups"] = ["Only the first results fit in the caption:"]
        resp["followups"].extend(overflow_lines)
    return resp


_HANDLERS = {
    "menu": _h_menu, "about": _h_about, "ping": _h_ping,
    "text_menu": _h_text_menu, "random_menu": _h_random_menu,
    "fun_menu": _h_fun_menu, "time_menu": _h_time_menu,
    "image_menu": _h_image_menu, "media_menu": _h_media_menu,
    "download_menu": _h_download_menu, "ytmp3_menu": _h_ytmp3_menu,
    "notes_menu": _h_notes_menu, "reminders_menu": _h_reminders_menu,
    "calc": _h_calc,
    "upper": _h_upper, "lower": _h_lower, "title": _h_title,
    "reverse": _h_reverse, "count": _h_count,
    "b64": _h_b64, "unb64": _h_unb64,
    "md5": _h_md5, "sha1": _h_sha1, "sha256": _h_sha256, "hash": _h_hash,
    "urlencode": _h_urlencode, "urldecode": _h_urldecode,
    "json": _h_json, "password": _h_password, "uuid": _h_uuid,
    "random": _h_random, "dice": _h_dice, "coin": _h_coin,
    "choice": _h_choice, "ask": _h_ask,
    "even": _h_even, "odd": _h_odd, "prime": _h_prime,
    "time": _h_time, "city_time": _h_city_time, "unix": _h_unix,
    "days": _h_days, "countdown": _h_countdown,
    "weather": _h_weather, "dictionary": _h_dictionary,
    "quote": _h_quote, "joke": _h_joke, "fact": _h_fact,
    "qr": _h_qr, "note": _h_note, "notes": _h_notes,
    "remind": _h_remind, "reminders": _h_reminders,
    "cancel_reminder": _h_cancel_reminder, "clear_reminders": _h_clear_reminders,
    "download": _h_download, "ytmp3": _h_ytmp3,
    "sticker": _h_sticker, "convert": _h_convert,
    "media_info": _h_media_info,
    "ytsearch": _h_ytsearch,
}

# --------------------------------------------------------------------------
# inbound media

def _handle_media(user: str, msg: dict, mtype: str) -> Optional[dict]:
    payload = msg.get(mtype) or {}
    media_id = payload.get("id")
    mime = payload.get("mime_type") or "application/octet-stream"
    if not media_id:
        return None

    state = get_state(user)

    if state == "wait:sticker" and mtype == "image":
        clear_state(user)
        path = _tmp_file("img")
        if not api_client.download_media(media_id, path):
            return {"text": "Couldn't fetch your image file."}
        try:
            sticker = media_tools.image_to_sticker(path)
        except Exception as e:
            return {"text": f"Sticker failed: {e}"}
        return {"media_path": sticker, "media_type": "sticker",
                "caption": None, "filename": None}

    if state == "wait:convert" and mtype in ("audio", "video"):
        clear_state(user)
        path = _tmp_file("in")
        if not api_client.download_media(media_id, path):
            return {"text": "Couldn't fetch your file."}
        try:
            mp3 = media_tools.convert_to_mp3(path)
        except Exception as e:
            return {"text": f"Conversion failed: {e}"}
        return {"media_path": mp3, "media_type": "audio",
                "caption": "Converted to MP3",
                "filename": "audio.mp3"}

    if state == "wait:info":
        clear_state(user)
        path = _tmp_file("in")
        info_text = ""
        if api_client.download_media(media_id, path):
            try:
                info_text = media_tools.media_summary(path)
            except Exception:
                info_text = ""
        lines = ["*Media details*"]
        lines.append(f"Type: {mtype}")
        lines.append(f"MIME: {mime}")
        if info_text:
            lines.append("\n" + info_text)
        sha = payload.get("sha256", "")
        if sha:
            lines.append(f"SHA256 (b64): `{sha[:32]}…`")
        return {"text": "\n".join(lines)}

    # unsolicited media — ack with metadata + hints (no state involved)
    hints = f"\n\nWant a *sticker*? send `sticker`\nWant details? send `info`"
    if mtype == "audio" and payload.get("voice"):
        return {"text": "Voice note received ✓\n\nWant it as *MP3*? send `convert`, then re-send the audio." + hints}
    caption = payload.get("caption")
    extra = f" — “{caption}”" if caption else ""
    return {"text": f"Received *{mtype}*{extra}\nMIME: {mime}" + hints}

# --------------------------------------------------------------------------
# entry point used by the worker thread


def process_message(msg: dict) -> Optional[dict]:
    user = msg.get("from")
    if not user or not user.startswith("user:"):
        return None
    mtype = msg.get("type")

    if mtype == "reaction":
        return None  # acknowledgements are silent

    if mtype == "text":
        body = (msg.get("text") or {}).get("body", "")
        return _handle_text(user, body or "", msg)

    if mtype in ("image", "audio", "video", "document", "sticker"):
        return _handle_media(user, msg, mtype)

    return None


def _handle_text(user: str, text: str, msg: dict) -> Optional[dict]:
    first, _, rest = text.strip().partition(" ")
    first = first.strip()
    rest = rest.strip()

    # multistep state machine
    state = get_state(user)
    if state:
        if first.lower() in ("menu", "cancel", "stop"):
            clear_state(user)
            return _h_menu(user, "", msg)
        if state in ("wait:download", "wait:mp3"):
            clear_state(user)
            if tools.is_url(text.strip()):
                return _do_download(user, text.strip(), "video" if state == "wait:download" else "audio")
            return {"text": "That doesn't look like a link. Send something like `https://…`"}
        if state == "wait:remind":
            if not text.strip():
                return {"text": "Tell me e.g. `in 10 take a break`"}
            clear_state(user)
            return _h_remind(user, text.strip(), msg)
        if state in ("wait:sticker", "wait:convert", "wait:info"):
            return {"text": "Ok — now send me the *media file* (image / audio / video)"}

    if not text.strip():
        return None

    # special: inline JSON pretty-print
    if first.lower() == "json":
        return _h_json(user, rest, msg)
    if first.lower().startswith("json:"):
        return _h_json(user, text.strip()[5:], msg)

    intent = menus.resolve_intent(first)
    if intent is None:
        intent = menus.resolve_intent(text.strip().split()[0]) if text.strip() else None
    handler = _HANDLERS.get(intent)
    if handler is None:
        return _unknown_hint()

    try:
        return handler(user, rest, msg)
    except (ValueError, ZeroDivisionError, OverflowError) as e:
        return {"text": f"{e}"}
    except RuntimeError as e:
        return {"text": f"{e}"}
    except Exception as e:
        return {"text": f"Something went wrong ({type(e).__name__}). Try again."}


def _unknown_hint() -> dict:
    return {"text": (
        "I didn't understand that.\n\n"
        "Try: `menu` for the full command list, or jump straight in:\n"
        "• `weather lahore`\n• `dl <youtube link>`\n• `calc 2^10`\n• `qr https://example.com`")}