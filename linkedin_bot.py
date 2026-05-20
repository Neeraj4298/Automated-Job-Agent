import asyncio
import csv
import random
import re
import sys
from pathlib import Path
from typing import List, Optional, Dict

from loguru import logger
from playwright.async_api import Page, TimeoutError

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from browser.engine import BrowserEngine
from browser.timing import between_applications, page_load_buffer, pre_apply_delay, read_delay, scroll_delay, async_sleep
from config import settings
from exceptions import LoginError, BotDetectionError
from ai.llm_client import LLMClient

# ─────────────────────────────────────────────
#  Candidate profile snapshot (used in messages)
#  Real values must come from local .env, never from committed source.
# ─────────────────────────────────────────────
MY_NAME = settings.full_name.split()[0] if settings.full_name else "Candidate"
MY_SKILLS = settings.skills_summary or "Python, FastAPI, cloud, data engineering"
MY_COLLEGE = "Configured in resume"
MY_NOTICE = settings.available_start_date or "Configured locally"
MY_ACHIEVEMENT = settings.achievements or "built reliable backend and data systems"

# ─────────────────────────────────────────────
#  Outreach message templates
# ─────────────────────────────────────────────
TEMPLATES: Dict[str, str] = {

    # ── Connection request note (≤300 chars) ─────────────────────────
    "connect_recruiter": (
        "Hi [Name], I applied for [Job Title] at [Company]. "
        "I'm a Backend/AI Engineer with skills in Python, GCP, GenAI & LLMs. "
        "Please consider my profile and schedule an interview if there's a fit. "
        f"Thanks, {MY_NAME}!"
    ),
    "connect_alumni": (
        f"Hi [Name], I applied for [Job Title] at [Company]. "
        "I have strong skills in Python, GCP, GenAI & LLMs. "
        "Would you be open to providing a referral or connecting? "
        f"Thanks, {MY_NAME}!"
    ),
    "connect_manager": (
        "Hi [Name], I applied for [Job Title] at [Company]. "
        "I'm a Backend/AI Engineer with skills in Python, GCP, GenAI & LLMs. "
        "Please consider my profile for an interview. "
        f"Thanks, {MY_NAME}!"
    ),
    "connect_founder": (
        "Hi [Name], I applied for [Job Title] at [Company]. "
        "I'm a Backend/AI Engineer with skills in Python, GCP, GenAI & LLMs. "
        "Please consider my profile for an interview. "
        f"Thanks, {MY_NAME}!"
    ),

    # ── Referral DM (sent after connection is accepted) ──────────────
    "referral_dm": (
        "Hi [Name],\n\n"
        "I hope you're having a great week!\n\n"
        "I'm reaching out because I saw the **[Job Title]** opening at **[Company]** "
        f"and I'm very interested. I'm a Backend/AI Engineer ({MY_COLLEGE}) specialising "
        f"in {MY_SKILLS}. In my recent role I {MY_ACHIEVEMENT}.\n\n"
        "Given my strong alignment with the role, would you be open to submitting a quick "
        "employee referral for me? I've attached my resume and the job link below for "
        "your reference – just the Job ID is all that's usually needed on the internal portal!\n\n"
        "No worries at all if you don't have the bandwidth right now – I appreciate your "
        "time either way.\n\n"
        f"Best,\n{MY_NAME}\n"
        "**Job Link/ID:** [Insert Link]"
    ),

    # ── HR / Interview schedule request ─────────────────────────────
    "hr_schedule": (
        "Hi [Name],\n\n"
        f"I'm {MY_NAME}, a Backend/AI Engineer ({MY_COLLEGE}). I recently applied for "
        "the **[Job Title]** role at **[Company]** and am very excited about the opportunity.\n\n"
        f"I bring strong expertise in {MY_SKILLS}, and have {MY_ACHIEVEMENT}. "
        f"I'm available to join in {MY_NOTICE}.\n\n"
        "Could you please consider scheduling an interview or sharing the next steps? "
        "I'd be happy to send across my resume / portfolio.\n\n"
        f"Thank you!\nBest regards,\n{MY_NAME}"
    ),
}


class LinkedInBot:
    """
    Autonomous bot for applying to LinkedIn jobs (Easy Apply only) and
    networking / referral outreach using Playwright.

    New in this version
    ───────────────────
    • Saves LinkedIn profile URL in recruiters.csv
    • CSV columns: Name | Email | Job Title | Company | LinkedIn Profile URL
    • Skips jobs with an external "Apply" button (only Easy Apply is used)
    • Sends referral DM after connecting with alumni / employees
    • Sends interview-schedule request to HR / Recruiters
    • Mentions the candidate's skills explicitly in every outreach message
    """

    # ── CSV columns ──────────────────────────────────────────────────
    CSV_HEADERS = [
        "RecruiterName", "RecruiterEmail", "RecruiterPhone", "JobTitle",
        "Company", "RoleType", "Status", "DateSent", "LinkedInProfile"
    ]

    def __init__(self):
        self.creds = settings.get_credentials("linkedin.com")
        self.queries = [
            "AI Engineer",
            "Python Backend Developer",
            "Software Engineer",
            "Data Engineer",
        ]
        self.recruiters_csv = PROJECT_ROOT.parent / "recruiter_outreach" / "recruiters.csv"
        self.saved_answers = {}
        self._ensure_csv_exists()
        self.llm = LLMClient()

    # ── Initialisation helpers ───────────────────────────────────────

    def _ensure_csv_exists(self) -> None:
        """Ensure the recruiter CSV exists with the updated headers."""
        self.recruiters_csv.parent.mkdir(parents=True, exist_ok=True)
        if not self.recruiters_csv.exists():
            with open(self.recruiters_csv, "w", newline="") as f:
                csv.writer(f).writerow(self.CSV_HEADERS)
        else:
            # Migrate old CSV to include LinkedInProfile column if needed
            with open(self.recruiters_csv, "r", newline="") as f:
                first_line = f.readline()
            if "LinkedInProfile" not in first_line:
                logger.info("Migrating recruiters.csv to include LinkedInProfile column...")
                rows = []
                with open(self.recruiters_csv, "r", newline="") as f:
                    reader = csv.reader(f)
                    for row in reader:
                        rows.append(row)
                
                if not rows:
                    rows = [self.CSV_HEADERS]
                else:
                    rows[0].append("LinkedInProfile")
                    for i in range(1, len(rows)):
                        rows[i].append("")
                        
                with open(self.recruiters_csv, "w", newline="") as f:
                    csv.writer(f).writerows(rows)

    def _save_recruiter(
        self,
        name: str,
        email: str,
        job_title: str,
        company: str,
        linkedin_url: str = "",
    ) -> None:
        """Append one recruiter row to the CSV (deduplicates by LinkedIn URL or email)."""
        existing_urls  = set()
        existing_emails = set()
        try:
            with open(self.recruiters_csv, "r", newline="") as f:
                for row in csv.DictReader(f):
                    if row.get("LinkedInProfile"):
                        existing_urls.add(row["LinkedInProfile"].strip())
                    if row.get("RecruiterEmail"):
                        existing_emails.add(row["RecruiterEmail"].strip())
        except Exception:
            pass

        if linkedin_url and linkedin_url in existing_urls:
            logger.debug("Recruiter already in CSV (URL match).")
            return
        if email and email in existing_emails:
            logger.debug("Recruiter already in CSV (email match).")
            return

        with open(self.recruiters_csv, "a", newline="") as f:
            csv.writer(f).writerow([name, email, "", job_title, company, "", "New", "", linkedin_url])
        logger.success("Saved recruiter contact.")

    # ── Login ────────────────────────────────────────────────────────

    async def login(self, page: Page) -> None:
        if not self.creds or "email" not in self.creds or "password" not in self.creds:
            raise LoginError("No LinkedIn credentials found in .env.")

        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        await async_sleep(page_load_buffer() + 3)

        if "feed" in page.url or await page.locator("a[href*='/feed/']").first.is_visible():
            logger.info("Already logged in.")
            return

        logger.info("Logging in to LinkedIn…")
        await page.locator("#username").fill(self.creds["email"])
        await async_sleep(0.5)
        await page.locator("#password").fill(self.creds["password"])
        await async_sleep(0.5)
        await page.locator("button[type='submit']").click()

        try:
            await page.wait_for_url("**/feed/**", timeout=20000)
            logger.info("Logged in successfully.")
        except TimeoutError:
            if await page.locator(".challenge-dialog, #captcha-internal").first.is_visible():
                raise BotDetectionError("CAPTCHA / 2FA detected. Please solve manually.")
            raise BotDetectionError("Timeout after login. Manual intervention needed.")

    # ── Daily network hack ───────────────────────────────────────────

    async def network_hack(self, page: Page) -> None:
        logger.info("▶ Daily Network Hack…")

        # Accept pending invitations
        try:
            await page.goto("https://www.linkedin.com/mynetwork/", wait_until="domcontentloaded", timeout=30000)
            await async_sleep(page_load_buffer())
            count = 0
            for btn in await page.locator("button[aria-label^='Accept']").all():
                if count >= 5:
                    break
                await btn.click()
                await async_sleep(1)
                count += 1
        except Exception as e:
            logger.debug(f"Accept invitations failed: {type(e).__name__}")

        # Feed engagement
        try:
            await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
            await async_sleep(page_load_buffer())
            liked = 0
            for _ in range(3):
                await page.mouse.wheel(0, random.randint(1000, 2000))
                await async_sleep(random.uniform(1.5, 3.5))
            for btn in await page.locator("button.react-button__trigger, button[aria-label*='Like'][aria-label*='React']").all():
                if liked >= 2:
                    break
                if await btn.get_attribute("aria-pressed") == "false":
                    await btn.scroll_into_view_if_needed()
                    await async_sleep(random.uniform(1.0, 2.0))
                    await btn.click(delay=random.randint(50, 150))
                    liked += 1
                    logger.info("Liked a feed post.")
                    await async_sleep(random.uniform(2.0, 4.0))
        except Exception as e:
            logger.warning(f"Feed engagement failed: {type(e).__name__}")

        # Send 5 recruiter connection requests
        try:
            await page.goto(
                "https://www.linkedin.com/search/results/people/?keywords=Recruiter%20Tech",
                wait_until="domcontentloaded", timeout=30000,
            )
            await async_sleep(page_load_buffer())
            sent = 0
            for btn in await page.locator("button:has-text('Connect')").all():
                if sent >= 5:
                    break
                await btn.scroll_into_view_if_needed()
                await async_sleep(random.uniform(1.0, 2.5))
                await btn.click(delay=random.randint(50, 150))
                await async_sleep(random.uniform(1.0, 2.0))
                send_btn = page.locator("button[aria-label='Send without a note'], button[aria-label='Send now']").first
                if await send_btn.is_visible():
                    await send_btn.click(delay=random.randint(50, 150))
                    sent += 1
                    logger.success("Sent general recruiter connection request.")
                else:
                    dismiss = page.locator("button[aria-label='Dismiss']").first
                    if await dismiss.is_visible():
                        await dismiss.click()
                await async_sleep(random.uniform(2.0, 4.0))
        except Exception as e:
            logger.debug(f"Recruiter connection requests failed: {type(e).__name__}")

    # ── Hidden jobs hack (post search) ──────────────────────────────

    async def hidden_jobs_hack(self, page: Page) -> None:
        logger.info("▶ Hidden Jobs Hack (Post Search)…")
        from urllib.parse import quote
        query = '("hiring" OR "looking for") AND ("AI Engineer" OR "Backend Developer") AND "Python"'
        url = f"https://www.linkedin.com/search/results/content/?datePosted=%22past-week%22&keywords={quote(query)}"

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await async_sleep(page_load_buffer())

            for post in (await page.locator(".feed-shared-update-v2").all())[:5]:
                await post.scroll_into_view_if_needed()
                await async_sleep(random.uniform(1.5, 3.5))

                # Comment "Interested, sending you a DM!"
                comment_btn = post.locator("button[aria-label*='Comment'], button.comment-button").first
                if await comment_btn.is_visible():
                    await comment_btn.click(delay=random.randint(50, 150))
                    await async_sleep(random.uniform(1.0, 2.0))
                    editor = post.locator(".ql-editor").first
                    if await editor.is_visible():
                        await editor.fill("Interested, sending you a DM!")
                        await async_sleep(random.uniform(1.0, 2.0))
                        submit = post.locator("button.comments-comment-box__submit-button").first
                        if await submit.is_visible():
                            await submit.click(delay=random.randint(50, 150))
                            logger.success("Commented on hidden-job post.")

                # Connect with poster
                poster_link = post.locator("a.update-components-actor__meta-link").first
                if await poster_link.is_visible():
                    poster_url = await poster_link.get_attribute("href")
                    await self._connect_with_user(page, poster_url, "Hidden Role", "your company")
        except Exception as e:
            logger.error(f"Hidden jobs workflow failed: {type(e).__name__}")

    # ── Email extraction ─────────────────────────────────────────────

    @staticmethod
    def _extract_emails(text: str) -> List[str]:
        emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
        return list(set(e for e in emails if not e.endswith("linkedin.com")))

    # ── Classify profile type ────────────────────────────────────────

    @staticmethod
    def _classify_profile(headline: str) -> str:
        hl = headline.lower()
        if any(k in hl for k in ["recruiter", "hr", "talent", "acquisition", "staffing"]):
            return "recruiter"
        if any(k in hl for k in ["founder", "ceo", "cto", "co-founder"]):
            return "founder"
        if any(k in hl for k in ["manager", "vp", "director", "head of", "lead"]):
            return "manager"
        return "alumni"

    # ── Build outreach message ───────────────────────────────────────

    @staticmethod
    def _build_message(template_key: str, name: str, job_title: str, company: str) -> str:
        tmpl = TEMPLATES.get(template_key, TEMPLATES["connect_recruiter"])
        msg = (
            tmpl
            .replace("[Name]", name)
            .replace("[Job Title]", job_title)
            .replace("[Company]", company)
        )
        return msg[:300] if "connect_" in template_key else msg

    # ── Execute job search ───────────────────────────────────────────

    async def _execute_search(self, page: Page, query: str) -> None:
        logger.info(f"🔍 Searching: {query}")
        from urllib.parse import quote
        url = (
            f"https://www.linkedin.com/jobs/search/"
            f"?f_E=2%2C3&f_TPR=r86400&f_WT=2&keywords={quote(query)}"
            f"&f_LF=f_AL"        # f_AL = Easy Apply filter
        )
        await page.goto(url, wait_until="domcontentloaded")
        await async_sleep(page_load_buffer())
        await self._process_job_pages(page)

    # ── Paginate job results ─────────────────────────────────────────

    async def _process_job_pages(self, page: Page) -> None:
        while True:
            logger.info("Processing job listings page…")
            try:
                await page.wait_for_selector(
                    ".jobs-search-results-list, .scaffold-layout__list", timeout=7000
                )
            except Exception:
                pass

            container = page.locator(".jobs-search-results-list, .scaffold-layout__list").first
            if not await container.is_visible():
                logger.info("No jobs found for this query.")
                break

            # Scroll the jobs panel to load all cards lazily
            for _ in range(5):
                try:
                    await container.evaluate("(n) => n.scrollTop = n.scrollHeight")
                except Exception:
                    pass
                await async_sleep(1.5)

            selector = "li.jobs-search-results__list-item, div.job-card-container, li.scaffold-layout__list-item"
            cards = await page.locator(selector).all()
            logger.info(f"Found {len(cards)} jobs on this page.")

            for i in range(len(cards)):
                try:
                    current_cards = await page.locator(selector).all()
                    if i >= len(current_cards):
                        break
                    await self._process_single_job_card(page, current_cards[i])
                except Exception as e:
                    logger.error(f"Card processing failed: {type(e).__name__}")

            # Next page
            try:
                active = page.locator("li[data-test-pagination-page-btn].active")
                if await active.is_visible():
                    cur = await active.get_attribute("data-test-pagination-page-btn")
                    if cur:
                        nxt = page.locator(f"li[data-test-pagination-page-btn='{int(cur)+1}'] button")
                        if await nxt.is_visible():
                            logger.info(f"Next page → {int(cur)+1}")
                            await nxt.click()
                            await async_sleep(page_load_buffer() + 2)
                            continue
                break
            except Exception:
                break

    # ── Process one job card ─────────────────────────────────────────

    async def _process_single_job_card(self, page: Page, card) -> None:
        await card.scroll_into_view_if_needed()
        await card.click()
        await async_sleep(scroll_delay() + 1)

        details = page.locator(
            ".jobs-search__job-details--container, .job-view-layout, .scaffold-layout__detail"
        ).first
        if not await details.is_visible():
            return

        # ── Job title & company ───────────────────────────────────────
        title_el = details.locator(
            "h2.job-details-jobs-unified-top-card__job-title, "
            "h2[class*='job-title'], h1[class*='job-title']"
        ).first
        job_title = (await title_el.inner_text()).strip() if await title_el.is_visible() else "Job"

        company_el = details.locator(
            "div.job-details-jobs-unified-top-card__company-name a, "
            "a[class*='company-name'], div[class*='company-name']"
        ).first
        company = (await company_el.inner_text()).strip() if await company_el.is_visible() else "Unknown Company"

        logger.info(f"📋 {job_title} @ {company}")

        # ── SKIP external-apply jobs ──────────────────────────────────
        easy_apply_btn = details.locator(
            "button.jobs-apply-button:has-text('Easy Apply'), "
            "button[aria-label*='Easy Apply']"
        ).first
        external_apply_btn = details.locator(
            "button.jobs-apply-button:not(:has-text('Easy Apply')), "
            "a[data-control-name='jobdetails_topcard_inapply']:not(:has-text('Easy Apply'))"
        ).first

        is_easy_apply     = await easy_apply_btn.is_visible()
        is_external_apply = await external_apply_btn.is_visible() and not is_easy_apply

        if is_external_apply:
            logger.info(f"⏭  Skipping external-apply job: {job_title} @ {company}")
            return

        # ── JD text (for email extraction) ───────────────────────────
        jd_el = details.locator("div.jobs-description-content__text, div[id='job-details']")
        jd_text = await jd_el.inner_text() if await jd_el.is_visible() else ""

        # ── Scenario C: email in JD ───────────────────────────────────
        emails = self._extract_emails(jd_text)
        if emails:
            logger.success("Scenario C: recruiter email found.")
            self._save_recruiter("Recruiter", emails[0], job_title, company, linkedin_url="")
            if is_easy_apply:
                await self._easy_apply(page, details, job_title, company)
            return

        # ── Scenario A: hirer card on job page ────────────────────────
        hirer_link = details.locator(
            ".hirer-card__hirer-information a, "
            ".jobs-poster a, "
            "div:has-text('Meet the hiring team') a[href*='/in/']"
        ).first
        if await hirer_link.is_visible():
            poster_url = await hirer_link.get_attribute("href") or ""
            logger.info("🤝 Scenario A — job poster found.")
            if is_easy_apply:
                await self._easy_apply(page, details, job_title, company)
            await self._connect_with_user(page, poster_url, job_title, company)
            return

        # ── Scenario B: search for recruiter ─────────────────────────
        logger.info("🔎 Scenario B — no poster; searching for recruiter…")
        if is_easy_apply:
            await self._easy_apply(page, details, job_title, company)
        await self._find_and_connect_recruiter(page, job_title, company)

    # ── Answer Inference ──────────────────────────────────────────────
    
    async def _infer_answer(self, question: str, options: List[str] = None) -> str:
        """Use LLM to infer the answer to a question based on the candidate profile."""
        profile_context = f"""Name: {MY_NAME}
Skills: {MY_SKILLS}
College: {MY_COLLEGE}
Notice Period: {MY_NOTICE}
Experience: Backend/AI Engineer, 3+ years python, 2 years GenAI/LLM/RAG/FastAPI.
Location: Bengaluru, India (willing to relocate to Bengaluru)
CTC: Current 7 LPA, Expected 14-18 LPA
Phone/Email: UNKNOWN (ask user)
"""
        system_prompt = "You are a deterministic job application assistant. Output ONLY valid JSON."
        user_prompt = f"""Based on this candidate profile:
{profile_context}

Answer this job application question: "{question}"
"""
        if options:
            user_prompt += f"\nOptions available: {options}\nYou MUST select one of the exact options provided, or 'UNKNOWN'."
            
        user_prompt += '\nReturn ONLY JSON in this format: {"answer": "your answer here"}\nIf you cannot determine the answer from the profile (like a specific phone number), return "UNKNOWN".'
        
        try:
            # We bypass the TASK_PROMPT_MAP in LLMClient by calling the underlying models directly
            if settings.has_gemini():
                res = self.llm._call_gemini(system_prompt, user_prompt)
            elif settings.has_anthropic():
                res = self.llm._call_anthropic(system_prompt, user_prompt)
            elif settings.has_openai():
                res = self.llm._call_openai(system_prompt, user_prompt)
            else:
                return ""
                
            if res and "answer" in res:
                ans = str(res["answer"]).strip()
                if ans.upper() == "UNKNOWN":
                    return ""
                return ans
        except Exception as e:
            logger.debug(f"LLM inference failed: {type(e).__name__}")
        return ""

    # ── Easy Apply flow ──────────────────────────────────────────────

    async def _easy_apply(self, page: Page, details, job_title: str, company: str) -> None:
        """Click Easy Apply and navigate the multi-step modal."""
        logger.info(f"⚡ Easy Apply → {job_title} @ {company}")
        try:
            btn = details.locator(
                "button.jobs-apply-button:has-text('Easy Apply'), "
                "button[aria-label*='Easy Apply']"
            ).first
            if not await btn.is_visible():
                logger.warning("Easy Apply button disappeared before click.")
                return
            await btn.click(delay=random.randint(50, 150))
            await async_sleep(random.uniform(2.0, 3.0))

            # Walk through pages of the modal
            max_steps = 10
            for step in range(max_steps):
                modal = page.locator("div[data-test-modal-id='easy-apply-modal'], div.jobs-easy-apply-modal").first
                if not await modal.is_visible():
                    break

                await async_sleep(1.0)

                # ── Fill form fields based on saved answers & interactively learn ────────────────
                try:
                    labels = await modal.locator("label").all()
                    for label in labels:
                        if not await label.is_visible():
                            continue
                        
                        question = (await label.inner_text()).strip()
                        clean_q = question.replace("*", "").strip().lower()
                        if not clean_q:
                            continue
                        
                        for_attr = await label.get_attribute("for")
                        if not for_attr:
                            continue
                            
                        field = modal.locator(f"#{for_attr}").first
                        if not await field.is_visible():
                            continue

                        answer = None
                        for q_key, a_val in self.saved_answers.items():
                            clean_key = q_key.lower().replace("*", "").strip()
                            if len(clean_key) < 4:
                                continue
                            if clean_key in clean_q or clean_q in clean_key:
                                answer = a_val
                                break
                        
                        # If no answer found, ask the user!
                        if not answer:
                            print("\n[?] LinkedIn screening question detected.")
                            
                            tag_name = await field.evaluate("el => el.tagName.toLowerCase()")
                            clean_options = None
                            if tag_name == "select":
                                options = await field.locator("option").all_inner_texts()
                                clean_options = [opt.strip() for opt in options if opt.strip() and opt.strip() != "Select an option"]
                                print(f"{len(clean_options)} options are available in the browser.")
                            
                            llm_suggestion = await self._infer_answer(question, clean_options)
                            if llm_suggestion:
                                print("A suggested answer is available.")
                                prompt_msg = "Your answer (press Enter to accept suggestion, or type your own): "
                            else:
                                prompt_msg = "Your answer (or press Enter to skip): "
                            
                            try:
                                user_input = await asyncio.to_thread(input, prompt_msg)
                                user_input = user_input.strip()
                                
                                if user_input:
                                    answer = user_input
                                elif llm_suggestion:
                                    answer = llm_suggestion
                                    
                                if answer:
                                    self.saved_answers[question.replace("*", "").strip()] = answer
                                    logger.success("Stored screening answer for this run.")
                            except BaseException as be:
                                logger.debug(f"Input interrupted: {type(be).__name__}")

                        if answer:
                            tag_name = await field.evaluate("el => el.tagName.toLowerCase()")
                            if tag_name == "select":
                                options = await field.locator("option").all_inner_texts()
                                best_opt = None
                                for opt in options:
                                    if opt.strip() == "Select an option": continue
                                    if answer.lower() == opt.strip().lower() or answer.lower() in opt.strip().lower():
                                        best_opt = opt.strip()
                                        break
                                if best_opt:
                                    await field.select_option(label=best_opt)
                                    logger.info("Selected screening option.")
                            elif tag_name == "input":
                                type_attr = await field.get_attribute("type")
                                if type_attr in ["text", "number", "tel", "email"]:
                                    await field.fill(answer)
                                    logger.info("Filled screening answer.")

                    fieldsets = await modal.locator("fieldset").all()
                    for fs in fieldsets:
                        if not await fs.is_visible():
                            continue
                        legend = fs.locator("legend, span.visually-hidden").first
                        if await legend.is_visible():
                            question = (await legend.inner_text()).strip()
                            clean_q = question.replace("*", "").strip().lower()
                            if not clean_q:
                                continue
                            
                            answer = None
                            for q_key, a_val in self.saved_answers.items():
                                clean_key = q_key.lower().replace("*", "").strip()
                                if clean_key in clean_q or clean_q in clean_key:
                                    answer = a_val
                                    break
                            
                            if not answer:
                                print("\n[?] LinkedIn radio screening question detected.")
                                try:
                                    user_input = await asyncio.to_thread(input, "Your answer (or press Enter to skip): ")
                                    user_input = user_input.strip()
                                    if user_input:
                                        answer = user_input
                                        self.saved_answers[question.replace("*", "").strip()] = answer
                                        logger.success("Stored screening answer for this run.")
                                except BaseException as be:
                                    logger.debug(f"Input interrupted: {type(be).__name__}")
                                    
                            if answer:
                                # Sometimes answer is 'Yes' but radio is 'Yes' or 'Yes.'
                                radio_label = fs.locator(f"label:has-text('{answer}'), label:has-text('{answer.capitalize()}')").first
                                if await radio_label.is_visible():
                                    await radio_label.click()
                                    logger.info("Selected screening radio option.")
                except Exception as e:
                    logger.debug(f"Form filling error: {type(e).__name__}")

                # Try "Next" first, then "Review", then "Submit"
                for label in ["Next", "Review", "Submit application"]:
                    btn_next = modal.locator(f"button[aria-label='{label}'], button:has-text('{label}')").first
                    if await btn_next.is_visible():
                        await btn_next.click(delay=random.randint(50, 150))
                        logger.info(f"  Easy Apply step {step+1}: clicked '{label}'")
                        await async_sleep(random.uniform(1.5, 2.5))

                        # Check for form validation errors
                        error_el = modal.locator(".artdeco-inline-feedback--error, div[id*='error'], span[id*='error']").first
                        if await error_el.is_visible():
                            logger.warning(f"Form validation error detected on step {step+1}.")
                            print("\n[!] The form has errors (e.g., missing or unsupported fields).")
                            print("[!] Please fix them manually in the browser window.")
                            try:
                                await asyncio.to_thread(input, "Press Enter here after you have fixed the issue (or to just retry): ")
                            except BaseException as be:
                                logger.debug(f"Input interrupted: {type(be).__name__}")
                            
                            # Re-click the button after manual intervention
                            if await btn_next.is_visible():
                                await btn_next.click(delay=random.randint(50, 150))
                                await async_sleep(random.uniform(1.5, 2.5))
                                
                        break
                else:
                    # No recognisable button found — check for "Done" (post-submit)
                    done = modal.locator("button[aria-label='Done'], button:has-text('Done')").first
                    if await done.is_visible():
                        await done.click(delay=random.randint(50, 150))
                        logger.success(f"✅ Applied (Easy Apply): {job_title} @ {company}")
                        
                        # Handle the "Keep track of your applications" toast/popup
                        await async_sleep(1.0)
                        not_now_btn = page.locator("button:has-text('Not now'), button:has-text('No, not now')").first
                        if await not_now_btn.is_visible():
                            await not_now_btn.click(delay=random.randint(50, 150))
                        break
                    # Dismiss any unexpected modal
                    close = modal.locator("button[aria-label='Dismiss']").first
                    if await close.is_visible():
                        await close.click()
                    break

            # ── Generic Post-Apply Cleanup ────────────────────────────────
            await async_sleep(1.5)
            post_apply_not_now = page.locator("button:has-text('Not now'), button:has-text('No, not now')").first
            if await post_apply_not_now.is_visible():
                await post_apply_not_now.click(delay=random.randint(50, 150))
                logger.info("    Dismissed generic post-apply tracking modal.")
                
            dismiss_toast = page.locator("button[aria-label='Dismiss']").first
            if await dismiss_toast.is_visible():
                try:
                    await dismiss_toast.click(delay=50)
                except Exception:
                    pass

            await async_sleep(between_applications())
        except Exception as e:
            logger.error(f"Easy Apply failed: {type(e).__name__}")

    # ── Scenario B helper: find & connect recruiter ──────────────────

    async def _find_and_connect_recruiter(self, page: Page, job_title: str, company: str) -> None:
        from urllib.parse import quote
        
        # 1. Clean company name (remove common suffixes that mess up search)
        clean_company = re.sub(r'(?i)\b(hq|ltd|inc|llc|technologies|private|limited|corp|corporation)\b', '', company)
        clean_company = re.sub(r'[.,]', '', clean_company).strip()
        if not clean_company:
            clean_company = company

        # 2. Iterate through different job titles to find the HR
        search_roles = [
            "Recruiter",
            "Talent Acquisition",
            "HR",
            "Human Resources",
            "Founder"
        ]

        sp = await page.context.new_page()
        try:
            for role in search_roles:
                search_query = f"{clean_company} {role}"
                logger.info(f"🔎 Trying hack: searching '{search_query}'...")
                search_url = (
                    f"https://www.linkedin.com/search/results/people/"
                    f"?keywords={quote(search_query)}"
                )
                
                await sp.goto(search_url, wait_until="domcontentloaded")
                await async_sleep(page_load_buffer())

                # 3. Specifically look for a person profile containing '/in/'
                person_links = await sp.locator("li.reusable-search__result-container a.app-aware-link[href*='/in/']").all()
                valid_url = None
                for link in person_links:
                    url = await link.get_attribute("href")
                    if url and "/in/" in url:
                        valid_url = url
                        break
                        
                if valid_url:
                    logger.success(f"🎯 Found recruiter/HR via query '{search_query}'")
                    await self._connect_with_user(sp, valid_url, job_title, company)
                    return
                else:
                    logger.debug(f"No result for query '{search_query}'.")
                    
            logger.warning(f"Exhausted all search hacks. No recruiter found for {company}.")
        except Exception as e:
            logger.error(f"Scenario B recruiter search failed: {type(e).__name__}")
        finally:
            await sp.close()

    # ── Send referral / schedule DM ──────────────────────────────────

    async def _send_dm(self, page: Page, name: str, profile_type: str, job_title: str, company: str) -> None:
        """
        Send a direct message:
        - Recruiter / HR  → interview-schedule request
        - Alumni / Manager / Founder → referral request
        """
        if profile_type in ("recruiter",):
            template_key = "hr_schedule"
            action_label = "interview-schedule request"
        else:
            template_key = "referral_dm"
            action_label = "referral DM"

        message = self._build_message(template_key, name, job_title, company)

        try:
            # Open messaging overlay
            msg_btn = page.locator(
                "button[aria-label*='Message'], a[aria-label*='Message'], "
                "button:has-text('Message')"
            ).first
            if not await msg_btn.is_visible():
                logger.warning("Message button not visible; skipping DM.")
                return

            await msg_btn.click(delay=random.randint(50, 150))
            await async_sleep(random.uniform(2.0, 3.0))

            # Compose box
            editor = page.locator(
                ".msg-form__contenteditable, div[contenteditable='true'][aria-label*='message']"
            ).first
            if await editor.is_visible():
                await editor.click()
                await editor.fill(message)
                await async_sleep(random.uniform(1.0, 2.0))

                send_btn = page.locator(
                    "button.msg-form__send-button, button[type='submit'][aria-label*='Send']"
                ).first
                if await send_btn.is_visible():
                    await send_btn.click(delay=random.randint(50, 150))
                    logger.success("DM sent.")
                else:
                    logger.warning("Send button not found in DM composer.")
            else:
                logger.warning("DM composer editor not visible.")

            # Close the overlay
            close = page.locator(
                "button[aria-label='Close your conversation'], "
                "button[aria-label='Dismiss']"
            ).first
            if await close.is_visible():
                await close.click()
            await async_sleep(random.uniform(1.5, 2.5))
        except Exception as e:
            logger.error(f"DM failed: {type(e).__name__}")

    # ── Core: connect + save to CSV ──────────────────────────────────

    async def _connect_with_user(
        self,
        page: Page,
        profile_url: str,
        job_title: str,
        company: str,
        send_dm_after: bool = True,
    ) -> None:
        """
        1. Visit profile
        2. Extract name, headline, & profile URL
        3. Save to recruiters.csv (with LinkedIn profile URL)
        4. Send tailored connection request
        5. Optionally send referral / schedule DM
        """
        # Normalise URL (remove query params)
        clean_url = profile_url.split("?")[0].rstrip("/") if profile_url else ""
        if not clean_url:
            logger.warning("Empty profile URL; skipping.")
            return

        cp = await page.context.new_page()
        try:
            await cp.goto(clean_url, wait_until="domcontentloaded")
            await async_sleep(page_load_buffer())

            # ── Name ──────────────────────────────────────────────────
            name_el = cp.locator("h1.text-heading-xlarge, h1[class*='text-heading']").first
            full_name = (await name_el.inner_text()).strip() if await name_el.is_visible() else "there"
            first_name = full_name.split()[0] if full_name != "there" else "there"

            # ── Headline ─────────────────────────────────────────────
            headline_el = cp.locator("div.text-body-medium.break-words").first
            headline = (await headline_el.inner_text()).strip() if await headline_el.is_visible() else ""

            profile_type = self._classify_profile(headline)

            # ── Save to CSV ───────────────────────────────────────────
            self._save_recruiter(
                name=full_name,
                email="",               # no email from profile page
                job_title=job_title,
                company=company,
                linkedin_url=clean_url,
            )

            # ── Build connection note ─────────────────────────────────
            connect_key = f"connect_{profile_type}"
            note = self._build_message(connect_key, first_name, job_title, company)

            # ── Click Connect ─────────────────────────────────────────
            connect_btn = cp.locator(
                "button.pvs-profile-actions__action:has-text('Connect'), "
                "button[aria-label*='Connect']"
            ).first

            if not await connect_btn.is_visible():
                more = cp.locator("button[aria-label='More actions'], button:has-text('More')").first
                if await more.is_visible():
                    await more.click(force=True)
                    await async_sleep(1.5)
                    dd_connect = cp.locator(
                        "div.artdeco-dropdown__content-inner li:has-text('Connect'), "
                        "div.artdeco-dropdown__content-inner div:has-text('Connect'), "
                        "div.artdeco-dropdown__content-inner span:has-text('Connect')"
                    ).first
                    if await dd_connect.is_visible():
                        connect_btn = dd_connect

            already_connected = False
            if await connect_btn.is_visible():
                await connect_btn.click(delay=random.randint(50, 150), force=True)
                await async_sleep(random.uniform(1.5, 3.0))

                # Email required?
                if await cp.locator("input[type='email'], input[name='email']").is_visible():
                    logger.warning("Email required to connect — skipping.")
                    dismiss = cp.locator("button[aria-label='Dismiss']").first
                    if await dismiss.is_visible():
                        await dismiss.click()
                    return

                # Add a note
                add_note = cp.locator("button[aria-label='Add a note'], button:has-text('Add a note')").first
                if await add_note.is_visible():
                    await add_note.click(delay=random.randint(50, 150))
                    await async_sleep(random.uniform(1.0, 2.0))

                    textarea = cp.locator("textarea[name='message'], textarea[id='custom-message']")
                    if await textarea.is_visible():
                        if hasattr(textarea, "press_sequentially"):
                            await textarea.press_sequentially(note, delay=random.randint(10, 40))
                        else:
                            await textarea.fill(note)
                        await async_sleep(random.uniform(1.0, 2.0))

                    send = cp.locator(
                        "button[aria-label='Send now'], "
                        "button[aria-label='Send connection request'], "
                        "button:has-text('Send')"
                    ).first
                    if await send.is_visible():
                        await send.click(delay=random.randint(50, 150))
                        logger.success("Connection request sent.")
                    else:
                        logger.warning("Send button not found in connection modal.")
                else:
                    logger.warning("'Add a note' button not found.")
                    dismiss = cp.locator("button[aria-label='Dismiss']").first
                    if await dismiss.is_visible():
                        await dismiss.click()
            else:
                # Could be already connected — check for Message button
                msg_visible = await cp.locator("button:has-text('Message')").first.is_visible()
                if msg_visible:
                    already_connected = True
                    logger.info("Already connected; sending DM directly.")
                else:
                    logger.warning("Connect button not found.")

            # ── DM (referral / schedule) ──────────────────────────────
            if send_dm_after and already_connected:
                await self._send_dm(cp, first_name, profile_type, job_title, company)

        except Exception as e:
            logger.error(f"Connect workflow failed: {type(e).__name__}")
        finally:
            await cp.close()
            await async_sleep(between_applications())

    # ── Main entry ───────────────────────────────────────────────────

    async def run(self) -> None:
        async with BrowserEngine(headless=settings.headless) as engine:
            page = await engine.new_page()

            await self.login(page)
            await self.network_hack(page)
            await self.hidden_jobs_hack(page)

            for query in self.queries:
                await self._execute_search(page, query)


# ── Runner ───────────────────────────────────────────────────────────

async def run_linkedin_routine():
    bot = LinkedInBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(run_linkedin_routine())
