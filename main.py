"""MADI BOT — all-in-one WhatsApp Agent Platform bot.

Threads
-------
bin-updater background download/update of the runtime binaries (see bootstrap)
poller    single long-poll loop on GET /agent/v1/updates, advancing next_offset
worker    processes inbound messages (reads receipts, typing, routing)
sender    serializes ALL outbound traffic (rate-limited, ordered)
reminders fires due reminders into the sender queue
cleaner   periodically removes stale downloaded/transcoded files

Offset handling follows the developer manual: a brand-new data folder starts
with an offset-less poll (only new traffic) ONCE, then resumes from the
persisted next_offset on every restart.
"""
import json
import queue
import sys
import threading
import time
from typing import Optional

from config.configure_bot import (AGENT_API_KEY, POLL_BACKOFF_TIMEOUT,
                                  STATE_FILE)
from utilities import api_client, bootstrap, handlers, media_tools, scheduler, tools

work_q: "queue.Queue[dict]" = queue.Queue(maxsize=200)
send_q: "queue.Queue[dict]" = queue.Queue(maxsize=200)

_LOG = sys.stderr.write


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    _LOG(f"[{ts}] {msg}\n")


# --------------------------------------------------------------------------
# persistent lightweight state (offset, initialized flag)

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


def _get_state() -> dict:
    return _load_state()


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False),
                              encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------------------
# sender

def chunk_text(text: str, limit: int = 4000):
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for ln in text.splitlines():
        if len(ln) > limit:
            if cur:
                out.append(cur)
                cur = ""
            while ln:
                out.append(ln[:limit])
                ln = ln[limit:]
            continue
        cand = f"{cur}\n{ln}" if cur else ln
        if len(cand) > limit:
            out.append(cur)
            cur = ln
        else:
            cur = cand
    if cur:
        out.append(cur)
    return out


def deliver(to: str, resp: dict) -> None:
    if not to or not resp:
        return
    followups = resp.get("followups") or []
    if isinstance(followups, str):
        followups = [followups]
    text = resp.get("text")
    if text:
        for part in chunk_text(text):
            api_client.send_text(to, part)
        for f in followups:
            for part in chunk_text(f):
                api_client.send_text(to, part)
        return
    path = resp.get("media_path")
    if not path:
        for f in followups:
            for part in chunk_text(f):
                api_client.send_text(to, part)
        return
    mtype = resp.get("media_type") or "document"
    media_id = api_client.upload_media(path, tools.mime_for(path))
    if not media_id:
        api_client.send_text(to, "Media upload failed (file too large or unsupported type).")
        return
    caption = resp.get("caption") or ""
    api_client.send_media(to, mtype, media_id,
                          caption=caption or None,
                          filename=resp.get("filename"))
    for f in followups:
        for part in chunk_text(f):
            api_client.send_text(to, part)


def sender_loop() -> None:
    while True:
        item = send_q.get()
        try:
            deliver(item.get("to"), item.get("resp"))
        except Exception as e:
            log(f"[sender] {type(e).__name__}: {e}")
        finally:
            send_q.task_done()


# --------------------------------------------------------------------------
# worker (message processing)

def _handle_inbound(msg: dict) -> None:
    mtype = msg.get("type")
    if msg.get("id"):
        wants_typing = mtype in ("text", "image", "audio", "video",
                                 "document", "sticker")
        try:
            api_client.mark_read(msg["id"], typing=wants_typing)
        except Exception:
            pass

    resp: Optional[dict] = None
    try:
        resp = handlers.process_message(msg)
    except Exception as e:
        log(f"[worker] process error: {type(e).__name__}: {e}")
        resp = {"text": "An error happened while processing that. Try again."}
    if resp:
        send_q.put({"to": msg.get("from"), "resp": resp})


def worker_loop() -> None:
    while True:
        msg = work_q.get()
        try:
            _handle_inbound(msg)
        except Exception as e:
            log(f"[worker] {type(e).__name__}: {e}")
        finally:
            work_q.task_done()


# --------------------------------------------------------------------------
# poller

def _ingest(data: dict) -> None:
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {}) or {}
            for contact in value.get("contacts", []):
                profile = (contact.get("profile") or {}).get("name")
                handlers.remember_profile(contact.get("wa_id"), profile)
            for msg in value.get("messages", []):
                if msg.get("type") in ("interactive", "button", "location"):
                    continue
                work_q.put(msg)


def poll_loop() -> None:
    state = _get_state()
    offset: Optional[int] = None
    if state.get("initialized"):
        offset = state.get("offset")

    backoff = 0
    while True:
        try:
            data = api_client.get_updates(offset=offset,
                                          timeout=POLL_BACKOFF_TIMEOUT)
        except Exception as e:
            log(f"[poll] exception {type(e).__name__}: {e}")
            time.sleep(3)
            backoff = 0
            continue

        if data is None:
            backoff = 0
            continue

        if "_error" in data:
            code = data["_error"]
            log(f"[poll] HTTP {code}")
            if code == 409:
                backoff = min((backoff or 1) * 3, 30)
                log(f"[poll] 409 conflict — backing off {backoff}s (another poll may be active)")
                time.sleep(backoff)
            else:
                backoff = min((backoff or 1) * 2, 15)
                time.sleep(backoff)
            continue

        backoff = 0
        try:
            _ingest(data)
        except Exception as e:
            log(f"[poll] ingest error: {e}")
        if "next_offset" in data:
            offset = data["next_offset"]
            next_state = _get_state()
            next_state["offset"] = offset
            next_state["initialized"] = True
            _save_state(next_state)


# --------------------------------------------------------------------------
# cleanup

def cleaner_loop(interval_minutes: int = 15) -> None:
    while True:
        time.sleep(interval_minutes * 60)
        try:
            media_tools.cleanup_old_files()
        except Exception as e:
            log(f"[cleaner] {e}")


# --------------------------------------------------------------------------
# entry

def main() -> None:
    if not AGENT_API_KEY:
        _LOG("AGENT_API_KEY is missing from .env — add it and retry.\n")
        sys.exit(1)

    log("MADI BOT starting…")
    log(f"poll timeout: {POLL_BACKOFF_TIMEOUT}s")

    bootstrap.ensure_binaries()
    bootstrap.start_updater()

    threads = [
        threading.Thread(target=poll_loop, name="poller", daemon=True),
        threading.Thread(target=worker_loop, name="worker", daemon=True),
        threading.Thread(target=sender_loop, name="sender", daemon=True),
        threading.Thread(target=cleaner_loop, name="cleaner", daemon=True),
    ]
    for t in threads:
        t.start()

    scheduler.run_daemon(
        send_cb=lambda user, resp: send_q.put({"to": user, "resp": resp}),
        name="reminders",
    )

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log("MADI BOT shutting down.")
        sys.exit(0)


if __name__ == "__main__":
    main()