import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.naukri.com/python-jobs")
        await page.wait_for_timeout(3000)
        
        # Look for filter dropdowns
        filters = await page.locator(".styles_filter-dropdown__*").all()
        print(f"Found {len(filters)} filter dropdowns")
        for f in filters:
            print(await f.inner_text())
            
        print("Looking for Experience text...")
        exp_elems = await page.locator("text='Experience'").all()
        for e in exp_elems:
            print(await e.evaluate("el => el.outerHTML")[:200])

        await browser.close()

asyncio.run(run())
