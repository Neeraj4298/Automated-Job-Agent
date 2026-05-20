import asyncio
import csv
import re
import sys
from pathlib import Path
from typing import List, Optional

from loguru import logger
from playwright.async_api import Page, TimeoutError

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from browser.engine import BrowserEngine
from browser.timing import between_applications, page_load_buffer, pre_apply_delay, read_delay, scroll_delay, async_sleep
from config import settings
from ai.llm_client import LLMClient
from exceptions import LoginError, BotDetectionError

class NaukriBot:
    """
    Autonomous bot for applying to jobs on Naukri using Playwright.
    """

    def __init__(self):
        """Initialize the bot, load credentials and verify paths."""
        self.creds = settings.get_credentials("naukri.com")
        self.queries = [
            'Python AND (FastAPI OR Flask) AND ("Generative AI" OR LLM OR RAG)',
            'Python AND FastAPI AND GCP AND (MongoDB OR SQL OR Microservices)',
            'Python AND (Dask OR Spark) AND ETL AND Databricks AND Pandas'
        ]
        self.recruiters_csv = PROJECT_ROOT.parent / "recruiter_outreach" / "recruiters.csv"
        self.session_answers = {}
        
        self._ensure_csv_exists()

    def _ensure_csv_exists(self) -> None:
        """Ensure the recruiter CSV exists with correct headers."""
        if not self.recruiters_csv.exists():
            self.recruiters_csv.parent.mkdir(parents=True, exist_ok=True)
            with open(self.recruiters_csv, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Name", "Email", "Job Title", "Company"])

    async def login(self, page: Page) -> None:
        """
        Log in to Naukri.com if not already logged in.

        Args:
            page (Page): The Playwright page instance.
            
        Raises:
            LoginError: If login credentials are not found or login fails.
            BotDetectionError: If a CAPTCHA or timeout is encountered.
        """
        if not self.creds or "email" not in self.creds or "password" not in self.creds:
            raise LoginError("No Naukri credentials found in .env (CREDENTIALS JSON string).")

        email = self.creds["email"]
        password = self.creds["password"]

        await page.goto("https://www.naukri.com/nlogin/login", wait_until="domcontentloaded")
        await async_sleep(page_load_buffer())

        if "login" not in page.url:
            logger.info("Already logged in to Naukri.")
            return

        logger.info("Logging in to Naukri...")
        
        await page.locator("#usernameField").fill(email)
        await async_sleep(0.5)
        
        await page.locator("#passwordField").fill(password)
        await async_sleep(0.5)
        
        await page.locator("button:has-text('Login')").first.click()
        
        try:
            await page.wait_for_url("**/mnjuser/homepage*", timeout=15000)
            logger.info("Successfully logged in.")
            await async_sleep(page_load_buffer())
        except TimeoutError:
            logger.warning("Timeout waiting for homepage after login. Potential CAPTCHA.")
            await async_sleep(10)
            raise BotDetectionError("Timeout waiting for homepage. Potential CAPTCHA or manual intervention needed.")

    async def profile_hack_9am(self, page: Page) -> None:
        """
        Execute the 9:00 AM Profile Hack to keep the profile fresh.

        Args:
            page (Page): The Playwright page instance.
        """
        logger.info("Executing the 9:00 AM Profile Hack...")
        await page.goto("https://www.naukri.com/mnjuser/profile", wait_until="domcontentloaded")
        await async_sleep(page_load_buffer())

        try:
            headline_edit = page.locator("span.edit, i.icon-edit, [class*='edit-icon']").first
            
            if not await headline_edit.is_visible():
                logger.warning("Could not find standard edit icon for Profile Hack.")
                 
            if await headline_edit.is_visible():
                await headline_edit.click()
                await async_sleep(2.0)
                
                textarea = page.locator("textarea").first
                current_text = await textarea.input_value()
                
                if len(current_text) > 0:
                    await textarea.fill(current_text[:-1])
                    await page.locator("button:has-text('Save')").locator("visible=true").first.click()
                    await async_sleep(2.0)
                    
                    await headline_edit.click()
                    await async_sleep(1.0)
                    await textarea.fill(current_text)
                    await page.locator("button:has-text('Save')").locator("visible=true").first.click()
                    await async_sleep(2.0)
                    logger.info("Profile Hack successfully registered as 'Updated Today'.")
                    return
                    
        except Exception as e:
            logger.warning(f"Profile headline update failed: {type(e).__name__}")

        # Fallback to Profile Summary
        try:
            summary_edit = page.locator("//span[text()='Profile summary']/following-sibling::span[contains(@class, 'edit')]")
            if await summary_edit.is_visible():
                await summary_edit.click()
                await async_sleep(1.0)
                
                textarea = page.locator("textarea[id='profileSummaryTxt']")
                current_text = await textarea.input_value()
                
                if len(current_text) > 0:
                    await textarea.fill(current_text[:-1])
                    await page.locator("button:has-text('Save')").locator("visible=true").first.click()
                    await async_sleep(2.0)
                    
                    await summary_edit.click()
                    await async_sleep(1.0)
                    await textarea.fill(current_text)
                    await page.locator("button:has-text('Save')").locator("visible=true").first.click()
                    logger.info("Profile Hack successfully registered via Profile Summary.")
        except Exception as e:
            logger.warning(f"Profile summary update failed: {type(e).__name__}")

    async def _extract_emails(self, text: str) -> List[str]:
        """
        Extract non-Naukri emails from text.

        Args:
            text (str): Job description text.

        Returns:
            List[str]: List of discovered email addresses.
        """
        pattern = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
        emails = re.findall(pattern, text)
        return [e for e in emails if not e.endswith("naukri.com")]

    async def _handle_chatbot(self, page: Page, job_title: str, company: str) -> None:
        """
        Interact with the Naukri chatbot to answer application screening questions.

        Args:
            page (Page): The current job application page.
            job_title (str): Title of the job.
            company (str): Company name.
        """
        max_questions = 20
        answered = 0
        
        while answered < max_questions:
            await async_sleep(2)
            
            bot_msgs = await page.locator(".botMsg, .bot-msg, .botMessage, .msg.bot, [class*='botMsg'], [class*='botMessage'], .message.bot, [class*='messageItem']").all()
            
            active_context = page
            if not bot_msgs:
                for frame in page.frames:
                    frame_msgs = await frame.locator(".botMsg, .bot-msg, .botMessage, .msg.bot, [class*='botMsg'], [class*='botMessage'], .message.bot, [class*='messageItem']").all()
                    if frame_msgs:
                        bot_msgs = frame_msgs
                        active_context = frame
                        break

            if not bot_msgs:
                break
                
            last_bot_msg = await bot_msgs[-1].inner_text()
            logger.info("Chatbot screening question detected.")
            
            if "successfully applied" in last_bot_msg.lower() or "application submitted" in last_bot_msg.lower() or "thank you" in last_bot_msg.lower():
                logger.success("Successfully applied via chatbot.")
                break
                
            chatbot_selectors = [
                ".chatbot", ".chat-window", ".chatbot_Drawer", "#chatbot-root",
                "[class*='chatbot']", "[class*='chatWindow']", ".drawer-content",
                ".bot-container", "[class*='botContainer']"
            ]
            chatbot_container = active_context.locator(", ".join(chatbot_selectors)).first
            
            option_selectors = [
                ".chip", ".option-btn", ".reply-option", "button.chat-option", 
                "[class*='chatOption']", "[class*='replyOption']", "[class*='chip']", 
                "button[class*='option']", "li[class*='option']", ".quick-reply", 
                ".pill", ".bot-option", "ul.options li", ".ssrc__label"
            ]
            
            if await chatbot_container.is_visible():
                options_locator = chatbot_container.locator(", ".join(option_selectors))
                raw_inputs = await chatbot_container.locator("input:not([type='hidden']), textarea, [contenteditable='true']").all()
            else:
                chatbot_container = active_context
                options_locator = chatbot_container.locator(", ".join(option_selectors))
                raw_inputs = await chatbot_container.locator("input:not([type='hidden']), textarea, [contenteditable='true']").all()

            input_box = None
            for inp in reversed(raw_inputs):
                if await inp.is_visible():
                    input_box = inp
                    break

            raw_options = await options_locator.all()
            options = []
            opt_texts = []
            for opt in raw_options:
                if await opt.is_visible():
                    t = await opt.inner_text()
                    if t.strip():
                        options.append(opt)
                        opt_texts.append(t.strip())
                    
            if options:
                logger.info("Screening options available.")
                if last_bot_msg in self.session_answers and self.session_answers[last_bot_msg] in opt_texts:
                    answer = self.session_answers[last_bot_msg]
                    logger.info("Found saved screening answer.")
                else:
                    print("\n[?] Chatbot screening question detected.")
                    print(f"{len(opt_texts)} options are available in the browser.")
                    try:
                        loop = asyncio.get_event_loop()
                        user_answer = await loop.run_in_executor(None, input, "Your choice (type exactly as shown): ")
                        answer = user_answer.strip()
                    except EOFError:
                        answer = opt_texts[0] if opt_texts else ""
                    
                    self.session_answers[last_bot_msg] = answer
                
                if answer and answer in opt_texts:
                    idx = opt_texts.index(answer)
                    await options[idx].click(force=True)
                elif options:
                    await options[0].click(force=True)
                    
                await async_sleep(0.5)
                send_btn = active_context.locator(".send-icon, .send-btn, button[title='Send'], [class*='sendIcon'], [class*='sendBtn'], button[class*='send'], .sendMsg").first
                if await send_btn.is_visible():
                    await send_btn.click(force=True)
                    
            elif input_box and await input_box.is_visible():
                if last_bot_msg in self.session_answers:
                    answer = self.session_answers[last_bot_msg]
                    logger.info("Found saved screening answer.")
                else:
                    print("\n[?] Chatbot screening question detected.")
                    try:
                        loop = asyncio.get_event_loop()
                        user_answer = await loop.run_in_executor(None, input, "Please provide the answer: ")
                        answer = user_answer.strip()
                    except EOFError:
                        answer = "Not Applicable"
                    
                    self.session_answers[last_bot_msg] = answer
                    
                await input_box.fill(str(answer))
                send_btn = active_context.locator(".send-icon, .send-btn, button[title='Send'], [class*='sendIcon'], [class*='sendBtn'], button[class*='send']").first
                if await send_btn.is_visible():
                    await send_btn.click(force=True)
                else:
                    await input_box.press("Enter")
            else:
                logger.warning("No input mechanisms found for chatbot. Might be stuck.")
                break
                
            answered += 1

    async def _execute_search(self, page: Page, query: str) -> None:
        """
        Execute a search query on Naukri and process results.

        Args:
            page (Page): The Playwright page instance.
            query (str): The boolean search string.
        """
        logger.info(f"Searching for: {query}")
        await page.goto("https://www.naukri.com/", wait_until="domcontentloaded")
        await async_sleep(page_load_buffer())
        
        search_input = page.locator(".suggestor-input").first
        await search_input.click(force=True)
        await search_input.fill(query)
        
        await self._apply_experience_filter_from_bar(page)
        
        try:
            await page.locator(".qsbSubmit").click(timeout=5000)
        except:
            await search_input.press("Enter")
            
        await async_sleep(page_load_buffer() + 2)
        await self._apply_freshness_filter(page)
        await self._process_job_pages(page)

    async def _apply_experience_filter_from_bar(self, page: Page) -> None:
        """Select experience from the top search bar dropdown."""
        try:
            exp_text = "3 years"
            if settings.experience_range:
                nums = re.findall(r'\d+', settings.experience_range)
                if nums:
                    exp_text = f"{nums[-1]} years"
                    
            logger.info(f"Attempting to select '{exp_text}' experience from search bar dropdown.")
            exp_dropdown = page.locator("#experienceDD, .experienceDD, .qsb-experience-wrap, input[placeholder*='experience' i]").first
            
            if await exp_dropdown.is_visible():
                await exp_dropdown.click(force=True)
                await async_sleep(1.5)
                
                exp_val = page.locator(f"xpath=//li[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{exp_text}')]").first
                if await exp_val.is_visible():
                    await exp_val.click(force=True)
                else:
                    logger.warning(f"Dropdown opened, but could not find '{exp_text}' option.")
        except Exception as e:
            logger.error(f"Failed to select experience from dropdown: {type(e).__name__}")

    async def _apply_freshness_filter(self, page: Page) -> None:
        """Apply 'Last 7 Days' freshness filter on the sidebar."""
        try:
            freshness_checkbox = page.locator("label[for='chk-Last 7 Days-fwDt-']")
            if await freshness_checkbox.is_visible():
                await freshness_checkbox.click()
                await async_sleep(page_load_buffer())
        except Exception as e:
            logger.debug(f"Could not click 7-day filter: {type(e).__name__}")

    async def _process_job_pages(self, page: Page) -> None:
        """Iterate through paginated job search results."""
        while True:
            logger.info("Processing job listings on current page...")
            job_cards = await page.locator("div[class*='srp-jobtuple-wrapper']").all()
            if not job_cards:
                job_cards = await page.locator("article.jobTuple").all()
                
            logger.info(f"Found {len(job_cards)} jobs on this page.")
            
            for i in range(len(job_cards)):
                try:
                    cards = await page.locator("div[class*='srp-jobtuple-wrapper']").all()
                    if not cards:
                        cards = await page.locator("article.jobTuple").all()
                        
                    if i >= len(cards):
                        break
                        
                    card = cards[i]
                    await self._process_single_job_card(page, card)
                    
                except Exception as e:
                    logger.error(f"Error processing job card: {type(e).__name__}")
            
            # Pagination
            try:
                next_btn = page.locator("a:has-text('Next')").first
                if not await next_btn.is_visible():
                    next_btn = page.locator("span:has-text('Next')").first
                    
                if await next_btn.is_visible():
                    logger.info("Moving to next page...")
                    await next_btn.click()
                    await async_sleep(page_load_buffer() + 2)
                else:
                    logger.info("No 'Next' button found. Finished processing query.")
                    break
            except Exception as e:
                logger.debug(f"Could not click Next button or reached end: {type(e).__name__}")
                break

    async def _process_single_job_card(self, page: Page, card: Page.locator) -> None:
        """Process an individual job listing card."""
        await card.scroll_into_view_if_needed()
        await async_sleep(scroll_delay())
        
        title_elem = card.locator("a.title")
        job_title = await title_elem.inner_text()
        company_elem = card.locator("a.comp-name")
        company = await company_elem.inner_text() if await company_elem.is_visible() else "Unknown"
        
        logger.info("Checking job.")
        
        if "accenture" in company.lower():
            logger.info("Skipping blocked company.")
            return
            
        job_url = await title_elem.get_attribute("href")
        if not job_url:
            return
            
        job_page = await page.context.new_page()
        await job_page.goto(job_url, wait_until="domcontentloaded")
        await async_sleep(page_load_buffer())
        
        await async_sleep(read_delay(300))
        
        jd_locator = job_page.locator("section.job-desc")
        if not await jd_locator.is_visible():
            jd_locator = job_page.locator("div.danger-html")
            
        jd_text = await jd_locator.inner_text() if await jd_locator.is_visible() else ""
        emails = await self._extract_emails(jd_text)
        
        if emails:
            self._handle_scenario_a(job_title, company, emails[0])
        else:
            await self._handle_scenario_c(job_page, job_title, company)
            
        await job_page.close()
        await async_sleep(between_applications())

    def _handle_scenario_a(self, job_title: str, company: str, email: str) -> None:
        """Handle Scenario A: Recruiter email is present."""
        logger.success("Scenario A: recruiter email found; skipping apply.")
        with open(self.recruiters_csv, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Recruiter", email, job_title, company])

    async def _handle_scenario_c(self, job_page: Page, job_title: str, company: str) -> None:
        """Handle Scenario C: Direct application via Naukri."""
        logger.info("Scenario C: No emails found. Attempting to apply...")
        
        apply_btn = job_page.locator("button:has-text('Apply')").first
        apply_on_company_btn = job_page.locator("button:has-text('Apply on Company Site')").first
        
        if await apply_on_company_btn.is_visible():
            logger.info("Job points to an external site. Skipping external application.")
        elif await apply_btn.is_visible():
            await async_sleep(pre_apply_delay())
            await apply_btn.click()
            await async_sleep(page_load_buffer())
            
            success_msg = job_page.locator("text='Applied successfully'").first
            success_msg_2 = job_page.locator("text='Successfully Applied'").first
            success_msg_3 = job_page.locator("text='Applied'").first
            
            if await success_msg.is_visible(timeout=2000) or await success_msg_2.is_visible(timeout=2000):
                logger.success("Successfully applied.")
            else:
                applied_btn = job_page.locator("button:has-text('Applied')").first
                if await applied_btn.is_visible(timeout=2000) or await success_msg_3.is_visible(timeout=2000):
                    logger.success("Successfully applied.")
                else:
                    chatbot = job_page.locator(".chatbot, .chat-window, .chatbot_Drawer, #chatbot-root, [class*='chatbot'], [class*='chatWindow']")
                    if await chatbot.first.is_visible(timeout=2000):
                        logger.info("Chatbot questionnaire detected. Initiating AI solver...")
                        try:
                            await self._handle_chatbot(job_page, job_title, company)
                        except Exception as e:
                            logger.error(f"Chatbot handling failed: {type(e).__name__}")
                    else:
                        logger.info("Clicked apply, but couldn't verify success message. (No chatbot detected)")
        else:
            logger.info("Apply button not found or already applied.")

    async def run(self) -> None:
        """
        Main execution flow for the Naukri bot.
        """
        async with BrowserEngine(headless=settings.headless) as engine:
            page = await engine.new_page()
            
            await self.login(page)
            await self.profile_hack_9am(page)
            
            for query in self.queries:
                await self._execute_search(page, query)

async def run_naukri_routine():
    """Wrapper function to instantiate and run NaukriBot."""
    bot = NaukriBot()
    await bot.run()

if __name__ == "__main__":
    asyncio.run(run_naukri_routine())
