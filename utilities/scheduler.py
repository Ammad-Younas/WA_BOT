"""Reminder engine: persistent scheduling with a background daemon that fires
due reminders through a callback (the sender queue).
"""
import json
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from config.configure_bot import REMINDERS_FILE

_lock = threading.Lock()


def _load() -> list:
    if REMINDERS_FILE.exists():
        try:
            rows = json.loads(REMINDERS_FILE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            rows = []
    else:
        rows = []
    return rows if isinstance(rows, list) else []


def _save(rows: list) -> None:
    REMINDERS_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                              encoding="utf-8")


def _fresh_id() -> int:
    rows = _load()
    return (max((r.get("id") or 0 for r in rows), default=0)) + 1


def parse_reminder(text: str) -> tuple:
    """Parse 'in <N> min <text>' or 'at <HH:MM [am|pm]> <text>'.

    Returns (due_unix_ts, note) or (None, None) if unparseable.
    """
    text = text.strip()
    m_in = re.match(r"^in\s+(\d+)\s*(?:min(?:ute)?s?|m)?\s*(.*)$", text, re.I)
    if m_in:
        minutes = max(1, int(m_in.group(1)))
        note = (m_in.group(2) or "Reminder ✔").strip()
        return time.time() + minutes * 60, note

    m_at = re.match(r"^at\s+(\d{1,2}):(\d{2})(?:\s*(am|pm))?\s*(.*)$", text, re.I)
    if m_at:
        hh, mm = int(m_at.group(1)), int(m_at.group(2))
        ap, note = m_at.group(3), (m_at.group(4) or "Reminder ✔").strip()
        if not (1 <= hh <= 12) or not (0 <= mm <= 59):
            return None, None
        if ap:
            a = ap.lower()
            if a == "pm" and hh != 12:
                hh += 12
            elif a == "am" and hh == 12:
                hh = 0
        if hh > 12 and not ap:  # accept 24h style like 14:30
            pass
        when = datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0)
        if when <= datetime.now():
            when += timedelta(days=1)
        return when.timestamp(), note
    return None, None


def add_reminder(user: str, due_ts: float, text: str) -> int:
    with _lock:
        rows = _load()
        rid = _fresh_id()
        rows.append({"id": rid, "user": user, "due": due_ts,
                     "text": text, "created": time.time()})
        _save(rows)
        rank = len([r for r in rows if r.get("user") == user])
        return rank


def _user_rows(user: str) -> list:
    rows = [r for r in _load() if r.get("user") == user]
    rows.sort(key=lambda r: r["due"])
    return rows


def list_reminders(user: str) -> str:
    rows = _user_rows(user)
    if not rows:
        return ("No active reminders.\n\n"
                "Set one with:\n`remind in 30 take a break`\n"
                "`remind at 18:30 go for a walk`")
    lines = [f"*Your reminders ({len(rows)})*"]
    for i, r in enumerate(rows, 1):
        when = time.strftime("%d %b %H:%M", time.localtime(r["due"]))
        lines.append(f"\n*{i}.* {when} — {r['text']}")
    lines.append("\n\nCancel: `cancel reminder <n>`  ·  Clear: `clear reminders`")
    return "\n".join(lines)


def remove_reminder(user: str, n: int) -> str:
    rows = _user_rows(user)
    try:
        target = rows[n - 1]
    except IndexError:
        return f"⚠️ You only have {len(rows)} reminder(s)."
    with _lock:
        all_rows = [r for r in _load() if r.get("id") != target["id"]]
        _save(all_rows)
    return f"Reminder #{n} cancelled."


def clear_reminders(user: str) -> str:
    with _lock:
        remaining = [r for r in _load() if r.get("user") != user]
        _save(remaining)
    return "All your reminders cleared."


def due_reminders(now_ts: float = None) -> list:
    if now_ts is None:
        now_ts = time.time()
    return [r for r in _load() if (r.get("due") or 0) <= now_ts]


def dismiss(ids) -> None:
    with _lock:
        remaining = [r for r in _load() if r.get("id") not in set(ids)]
        _save(remaining)


def run_daemon(send_cb: Callable, interval: int = 20, name: str = "reminders") -> threading.Thread:
    """Fire due reminders via send_cb(user_id, response_dict). Daemon thread."""

    def _loop():
        while True:
            try:
                due = due_reminders()
                if due:
                    for r in due:
                        send_cb(r.get("user"),
                                {"text": f"*Reminder* \n\n{r.get('text')}"})
                    dismiss([r["id"] for r in due])
            except Exception:
                pass
            time.sleep(interval)

    t = threading.Thread(target=_loop, name=name, daemon=True)
    t.start()
    return t