"""Thin, rate-limited client for the WhatsApp Agent Platform API.

Every endpoint has its own rolling 60-second counter (see the developer
manual, "Rate limits"). All outbound work is additionally serialized by the
sender thread in main.py so ordering to a recipient is guaranteed.
"""
import time
import threading
from pathlib import Path
from typing import Optional

import requests

from config.configure_bot import AUTH_HEADERS, BASE_URL

REQ_TIMEOUT = 35
MEDIA_TIMEOUT = 90


class RateLimiter:
    """Enforce a maximum number of calls per rolling 60-second window."""

    def __init__(self, rate: int):
        self.rate = rate
        self._slots: list[float] = []
        self._lock = threading.Lock()

    def wait(self) -> None:
        while True:
            with self._lock:
                now = time.time()
                self._slots = [t for t in self._slots if now - t < 60.0]
                if len(self._slots) < self.rate:
                    self._slots.append(now)
                    return
                sleep_for = 60.0 - (now - min(self._slots)) + 0.1
            time.sleep(sleep_for)


SEND_LIMITER = RateLimiter(12)
STATUS_LIMITER = RateLimiter(12)
POLL_LIMITER = RateLimiter(15)
MEDIA_LIMITER = RateLimiter(12)


def _call(method: str, path: str, limiter: RateLimiter,
          timeout: int = REQ_TIMEOUT, retries: int = 3,
          **kwargs) -> Optional[requests.Response]:
    """Perform an authenticated call honoring the endpoint rate limit.

    Retries 5xx / timeouts with exponential backoff. 4xx responses are
    returned as-is so the caller can react to the specific error.
    """
    for attempt in range(retries):
        limiter.wait()
        try:
            resp = requests.request(method, BASE_URL + path,
                                    headers=AUTH_HEADERS, timeout=timeout, **kwargs)
        except requests.RequestException:
            if attempt == retries - 1:
                return None
            time.sleep(2 ** attempt)
            continue
        if resp.status_code >= 500:
            if attempt == retries - 1:
                return resp
            time.sleep(2 ** attempt)
            continue
        return resp
    return None


# --------------------------------------------------------------------------
# Updates

def get_updates(offset: Optional[int] = None, limit: int = 50,
                timeout: int = 20) -> Optional[dict]:
    """Long-poll for inbound messages and statuses.

    Returns parsed JSON on 200, None on 204 (empty) or network failure.
    """
    params = {"limit": limit, "timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    resp = _call("GET", "/updates", POLL_LIMITER, params=params)
    if resp is None:
        return None
    if resp.status_code == 204:
        return None
    if resp.status_code != 200:
        return {"_error": resp.status_code, "_body": resp.text}
    try:
        return resp.json()
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Sending (serialized by the caller via a single sender thread)

def send_message(payload: dict) -> Optional[dict]:
    resp = _call("POST", "/messages", SEND_LIMITER, json=payload)
    if resp is None:
        return {"_error": "network"}
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = {"_raw": resp.text}
    return {"status": resp.status_code, **body}


def send_text(to: str, body: str, context: Optional[dict] = None) -> Optional[dict]:
    return send_message({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
        **({"context": context} if context else {}),
    })


def send_media(to: str, media_type: str, media_id: str,
               caption: Optional[str] = None,
               filename: Optional[str] = None) -> Optional[dict]:
    payload: dict = {"id": media_id}
    if caption:
        payload["caption"] = caption
    if media_type == "document" and filename:
        payload["filename"] = filename
    return send_message({
        "messaging_product": "whatsapp",
        "to": to,
        "type": media_type,
        media_type: payload,
    })


# --------------------------------------------------------------------------
# Statuses (read receipt + typing indicator)

def mark_read(message_id: str, typing: bool = False) -> bool:
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    if typing:
        payload["typing_indicator"] = {"type": "text"}
    resp = _call("POST", "/statuses", STATUS_LIMITER, json=payload)
    return bool(resp is not None and resp.status_code == 200)


# --------------------------------------------------------------------------
# Media

def upload_media(file_path: str, mime_type: str) -> Optional[str]:
    """Upload a file and return the media id, or None on failure."""
    with open(file_path, "rb") as fh:
        resp = _call(
            "POST", "/media", MEDIA_LIMITER, timeout=MEDIA_TIMEOUT,
            data={"messaging_product": "whatsapp", "type": mime_type},
            files={"file": (Path(file_path).name, fh, mime_type)},
        )
    if resp is None:
        return None
    try:
        return resp.json().get("id") if resp.status_code == 200 else None
    except ValueError:
        return None


def get_media_meta(media_id: str) -> Optional[dict]:
    resp = _call("GET", f"/media/{media_id}", MEDIA_LIMITER)
    if resp is None or resp.status_code != 200:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def download_media(media_id: str, dest_path: str) -> Optional[str]:
    """Fetch the stored bytes for a media id to dest_path."""
    meta = get_media_meta(media_id)
    if not meta or "url" not in meta:
        return None
    resp = requests.get(meta["url"], headers=AUTH_HEADERS, timeout=MEDIA_TIMEOUT)
    if resp.status_code != 200:
        return None
    with open(dest_path, "wb") as fh:
        fh.write(resp.content)
    return dest_path


def delete_media(media_id: str) -> bool:
    resp = _call("DELETE", f"/media/{media_id}", MEDIA_LIMITER)
    return bool(resp is not None and resp.status_code == 200)