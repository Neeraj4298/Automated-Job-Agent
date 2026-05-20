import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

async def debug_profile():
    async with async_playwright() as p:
        user_data_dir = "/tmp/naukri_profile" # or wherever BrowserEngine stores it
        # Actually BrowserEngine stores it in ~/.cache/job_agent or somewhere?
        # Let's import BrowserEngine
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from browser.engine import BrowserEngine
        
        async with BrowserEngine(headless=False, profile_name="naukri_profile") as engine:
            page = await engine.new_page()
            await page.goto("https://www.naukri.com/mnjuser/profile", wait_until="networkidle")
            
            # Print page text to see if we are logged in
            text = await page.inner_text("body")
            print("Page loaded. Checking for 'Resume headline'...")
            
            # Find all spans that contain edit
            edit_buttons = await page.locator("span.edit, i.icon-edit, span:has-text('edit')").all()
            print(f"Found {len(edit_buttons)} edit buttons.")
            for i, btn in enumerate(edit_buttons):
                try:
                    html = await btn.evaluate("el => el.outerHTML")
                    print(f"Edit {i}: {html}")
                except Exception as e:
                    print(f"Err on {i}: {e}")
                    
            # Let's dump all spans that might be edit buttons
            all_spans = await page.locator("span").all()
            print(f"Total spans on page: {len(all_spans)}")
            
            # Let's look for any element containing 'Resume headline'
            try:
                elem = page.locator("*:has-text('Resume headline')").last
                print("Resume Headline element:", await elem.evaluate("el => el.outerHTML"))
            except Exception as e:
                print(f"Resume headline text not found: {e}")

if __name__ == "__main__":
    asyncio.run(debug_profile())
