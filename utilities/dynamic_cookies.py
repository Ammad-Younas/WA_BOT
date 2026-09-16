"""Fetch YouTube PO Token and Visitor Data dynamically using a headless Chromium browser."""
import json
import time
from pathlib import Path
from typing import Optional

from config.configure_bot import DATA_DIR

TOKEN_CACHE = DATA_DIR / "dynamic_po_token.json"
CACHE_EXPIRY_SECONDS = 86400  # 24 hours


def fetch_youtube_token(force_refresh: bool = False) -> Optional[dict]:
    """Launch headless Chromium, visit YouTube, intercept API requests to extract PO token and visitor data.
    
    Returns a dict with 'po_token' and 'visitor_data' or None.
    """
    if not force_refresh and TOKEN_CACHE.exists():
        if time.time() - TOKEN_CACHE.stat().st_mtime < CACHE_EXPIRY_SECONDS:
            try:
                return json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            except ValueError:
                pass
            
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    extracted_token = None
    extracted_visitor = None

    def handle_request(request):
        nonlocal extracted_token, extracted_visitor
        # Intercept YouTube API calls that contain the tokens
        if "youtubei/v1/" in request.url and request.method == "POST":
            try:
                data = request.post_data_json
                if data:
                    if "context" in data:
                        client = data["context"].get("client", {})
                        if "visitorData" in client and not extracted_visitor:
                            extracted_visitor = client["visitorData"]
                            
                    if "serviceIntegrityDimensions" in data:
                        token_info = data["serviceIntegrityDimensions"].get("poToken", "")
                        if token_info and not extracted_token:
                            extracted_token = token_info
            except Exception:
                pass

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            # Listen to all network requests
            page.on("request", handle_request)
            
            # Go to a random YouTube video to force the player API to trigger
            page.goto("https://www.youtube.com/watch?v=jNQXAC9IVRw", wait_until="networkidle", timeout=30000)
            
            # Wait until both are extracted, up to 10 seconds
            for _ in range(10):
                if extracted_token and extracted_visitor:
                    break
                page.wait_for_timeout(1000)
                
            browser.close()
            
            if not extracted_token or not extracted_visitor:
                return None
                
            result = {
                "po_token": extracted_token,
                "visitor_data": extracted_visitor
            }
            TOKEN_CACHE.write_text(json.dumps(result), encoding="utf-8")
            return result
            
    except Exception as e:
        import sys
        sys.stderr.write(f"[dynamic_cookies] Failed to extract PO token via playwright: {e}\n")
        return None
