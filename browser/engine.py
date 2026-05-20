"""
browser/engine.py — Playwright browser engine with stealth configuration.

Provides an async context manager `BrowserEngine` that:
  1. Launches a Playwright-controlled Chromium browser
  2. Applies playwright-stealth patches to avoid bot detection
  3. Rotates User-Agent and viewport per session
  4. Avoids persistent browser profiles and plaintext cookie export
  5. Provides file upload helpers without logging local paths
"""

import asyncio
from typing import Optional

from loguru import logger
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

try:
    import playwright_stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False
    logger.warning(
        "playwright-stealth not installed. Bot detection risk is higher. "
        "Run: pip install playwright-stealth"
    )

from browser.useragents import get_random_ua, get_random_viewport


class BrowserEngine:
    """
    Async context manager wrapping a Playwright browser session.

    Usage:
        async with BrowserEngine(headless=False) as engine:
            page = await engine.new_page()
            await page.goto("https://example.com")
    """

    def __init__(self, headless: bool = True, slow_mo: int = 0, profile_name: Optional[str] = None):
        self.headless = headless
        self.slow_mo = slow_mo
        if profile_name:
            logger.debug("Persistent browser profiles are disabled; using ephemeral context.")
        self.profile_name = None
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self.user_agent: str = get_random_ua()
        self.viewport: dict = get_random_viewport()

    async def __aenter__(self) -> "BrowserEngine":
        self._playwright = await async_playwright().start()
        
        args = [
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--disable-infobars",
            "--disable-popup-blocking",
            "--disable-notifications",
        ]

        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=args,
        )
        self._context = await self._browser.new_context(
            user_agent=self.user_agent,
            viewport=self.viewport,
            locale="en-US",
            timezone_id="America/New_York",
            permissions=[],
            java_script_enabled=True,
            accept_downloads=True,
        )
        
        self._context.set_default_timeout(60000)
        logger.debug("Browser started.")
        return self

    async def __aexit__(self, *_) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.debug("Browser session closed.")

    async def new_page(self) -> Page:
        """Open a new page and apply stealth patches."""
        if not self._context:
            raise RuntimeError("BrowserEngine not started. Use async with.")
        page = await self._context.new_page()
        if STEALTH_AVAILABLE:
            if hasattr(playwright_stealth, "stealth_async"):
                await playwright_stealth.stealth_async(page)
            elif hasattr(playwright_stealth, "stealth"):
                # older version
                pass
            else:
                # v2.0+
                await playwright_stealth.Stealth().apply_stealth_async(page)
        return page

    # ── File upload ───────────────────────────────────────────────────

    async def safe_file_upload(
        self, page: Page, selector: str, file_path: str, retries: int = 2
    ) -> bool:
        """
        Upload a file. Handles both <input type="file"> and buttons
        that open a file chooser dialog.
        """
        for attempt in range(1, retries + 1):
            try:
                # Try as a standard file input first
                await page.set_input_files(selector, file_path, timeout=10000)
                logger.debug("File uploaded.")
                return True
            except Exception:
                try:
                    # Fallback for buttons that open a file chooser
                    async with page.expect_file_chooser() as fc_info:
                        await page.locator(selector).click()
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(file_path)
                    logger.debug("File uploaded.")
                    return True
                except Exception as e:
                    logger.warning(f"File upload attempt failed: {type(e).__name__}")
                    if attempt < retries:
                        await asyncio.sleep(2)
        return False

    # ── robots.txt check ──────────────────────────────────────────────

    @staticmethod
    async def check_robots_allowed(page: Page, url: str) -> bool:
        """
        Fetch /robots.txt and return True if the URL path is allowed
        for a generic User-Agent (*).  Returns True on any fetch error
        (fail open — the navigation check will catch actual blocks).
        """
        from urllib.parse import urlparse
        from urllib.robotparser import RobotFileParser

        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(robots_url)
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            allowed = rp.can_fetch("*", url)
            if not allowed:
                logger.warning("robots.txt blocks target URL.")
            return allowed
        except Exception:
            return True   # Fail open
