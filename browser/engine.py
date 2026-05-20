"""
browser/engine.py — Playwright browser engine with stealth configuration.

Provides an async context manager `BrowserEngine` that:
  1. Launches a Playwright-controlled Chromium browser
  2. Applies playwright-stealth patches to avoid bot detection
  3. Rotates User-Agent and viewport per session
  4. Manages cookie persistence
  5. Provides helper methods for screenshots and file uploads
"""

import asyncio
from pathlib import Path
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


SCREENSHOTS_DIR = Path("screenshots")
COOKIES_DIR = Path("queue/cookies")


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
        self.profile_name = profile_name
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self.user_agent: str = get_random_ua()
        self.viewport: dict = get_random_viewport()

        SCREENSHOTS_DIR.mkdir(exist_ok=True)
        COOKIES_DIR.mkdir(parents=True, exist_ok=True)
        if self.profile_name:
            Path(".playwright_profiles").mkdir(exist_ok=True)

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

        if self.profile_name:
            # Persistent context launches the browser AND context in one go
            profile_path = Path(".playwright_profiles") / self.profile_name
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_path),
                headless=self.headless,
                slow_mo=self.slow_mo,
                user_agent=self.user_agent,
                viewport=self.viewport,
                args=args,
                locale="en-US",
                timezone_id="America/New_York",
                permissions=["geolocation"],
                geolocation={"latitude": 40.7128, "longitude": -74.0060},
                java_script_enabled=True,
                accept_downloads=True,
            )
        else:
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
                permissions=["geolocation"],
                geolocation={"latitude": 40.7128, "longitude": -74.0060},
                java_script_enabled=True,
                accept_downloads=True,
            )
        
        self._context.set_default_timeout(60000)
        logger.debug(f"Browser started (Persistent: {bool(self.profile_name)}). UA: {self.user_agent[:60]}…")
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

    # ── Cookie persistence ────────────────────────────────────────────

    async def save_cookies(self, domain: str) -> None:
        """Persist cookies for a domain to disk."""
        if not self._context:
            return
        import json
        cookies = await self._context.cookies()
        domain_cookies = [c for c in cookies if domain in c.get("domain", "")]
        path = COOKIES_DIR / f"{domain.replace('.', '_')}.json"
        path.write_text(json.dumps(domain_cookies, indent=2))
        logger.debug(f"Saved {len(domain_cookies)} cookies for {domain}")

    async def load_cookies(self, domain: str) -> bool:
        """Load previously saved cookies for a domain. Returns True if found."""
        import json
        path = COOKIES_DIR / f"{domain.replace('.', '_')}.json"
        if not path.exists():
            return False
        try:
            cookies = json.loads(path.read_text())
            await self._context.add_cookies(cookies)
            logger.debug(f"Loaded {len(cookies)} cookies for {domain}")
            return True
        except Exception as e:
            logger.warning(f"Failed to load cookies for {domain}: {e}")
            return False

    # ── Screenshots ───────────────────────────────────────────────────

    async def take_screenshot(
        self, page: Page, job_id: str, suffix: str = "state"
    ) -> str:
        """
        Take a full-page screenshot and save to screenshots/.
        Returns the relative path to the screenshot file.
        """
        filename = f"{job_id[:16]}_{suffix}.png"
        path = SCREENSHOTS_DIR / filename
        try:
            await page.screenshot(path=str(path), full_page=True)
            logger.debug(f"Screenshot saved: {path}")
            return str(path)
        except Exception as e:
            logger.warning(f"Screenshot failed: {e}")
            return ""

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
                logger.debug(f"File uploaded via set_input_files: {file_path} → {selector}")
                return True
            except Exception:
                try:
                    # Fallback for buttons that open a file chooser
                    async with page.expect_file_chooser() as fc_info:
                        await page.locator(selector).click()
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(file_path)
                    logger.debug(f"File uploaded via file chooser: {file_path} → {selector}")
                    return True
                except Exception as e:
                    logger.warning(f"File upload attempt {attempt} failed: {e}")
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
                logger.warning(f"robots.txt blocks: {url}")
            return allowed
        except Exception:
            return True   # Fail open
