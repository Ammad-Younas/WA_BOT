"""Fetch YouTube cookies dynamically using a headless Chromium browser via Playwright."""
import time
from pathlib import Path
from typing import Optional

from config.configure_bot import DATA_DIR

COOKIE_CACHE = DATA_DIR / "dynamic_cookies.txt"
CACHE_EXPIRY_SECONDS = 86400


def format_to_netscape(cookies: list[dict]) -> str:
    """Format Playwright cookies into a Netscape HTTP Cookie File."""
    lines = [
        "# Netscape HTTP Cookie File",
        "# http://curl.haxx.se/rfc/cookie_spec.html",
        "# This is a generated file!  Do not edit.",
        ""
    ]
    for c in cookies:
        domain = c.get("domain", "")
        # Netscape format requires domain to start with a dot if it's broad
        if not domain.startswith(".") and not domain.startswith("www"):
            domain = "." + domain
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure", False) else "FALSE"
        
        # Expiry: playwright uses float/int for expires (Unix timestamp)
        # If -1 or missing, it's a session cookie, default to 0
        expires = c.get("expires", -1)
        if expires == -1:
            expires = 0
        expires = int(expires)
        
        name = c.get("name", "")
        value = c.get("value", "")
        
        lines.append(f"{domain}\t{include_subdomains}\t{path}\t{secure}\t{expires}\t{name}\t{value}")
    
    return "\n".join(lines)


def fetch_youtube_cookies(force_refresh: bool = False) -> Optional[Path]:
    """Launch headless Chromium, visit YouTube to generate PO token / cookies, and save them.
    
    Returns the path to the cookies file, or None if it failed or Playwright is not installed.
    """
    if not force_refresh and COOKIE_CACHE.exists():
        if time.time() - COOKIE_CACHE.stat().st_mtime < CACHE_EXPIRY_SECONDS:
            return COOKIE_CACHE
            
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            # Go to YouTube and wait for the page to settle so JS can execute and generate the PO Token
            page.goto("https://www.youtube.com", wait_until="domcontentloaded", timeout=30000)
            
            # Wait a few seconds for YouTube's bot-detection JS to run and set cookies
            page.wait_for_timeout(5000)
            
            # Additional interaction to mimic real user (sometimes required for PO token)
            page.mouse.move(500, 500)
            page.mouse.wheel(0, 500)
            page.wait_for_timeout(2000)
            
            cookies = context.cookies("https://www.youtube.com")
            browser.close()
            
            if not cookies:
                return None
                
            netscape_cookies = format_to_netscape(cookies)
            COOKIE_CACHE.write_text(netscape_cookies, encoding="utf-8")
            return COOKIE_CACHE
            
    except Exception as e:
        import sys
        sys.stderr.write(f"[dynamic_cookies] Failed to fetch cookies via playwright: {e}\n")
        return None
