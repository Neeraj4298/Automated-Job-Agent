import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.naukri.com/")
        inputs = await page.locator(".suggestor-input").all()
        print(f"Found {len(inputs)} suggestor inputs")
        for i, inp in enumerate(inputs):
            ph = await inp.get_attribute("placeholder")
            print(f"[{i}] placeholder: {ph}")
            html = await inp.evaluate("el => el.outerHTML")
            print(html[:100])
        await browser.close()

asyncio.run(run())
