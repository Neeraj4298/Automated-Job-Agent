import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto("https://www.naukri.com/python-jobs")
        await page.wait_for_timeout(5000)
        
        # Look for filter titles
        titles = await page.locator(".filter-title, [class*='styles_filter-title']").all()
        print(f"Found {len(titles)} filter titles")
        for t in titles:
            print(await t.inner_text())

        await browser.close()

asyncio.run(run())
