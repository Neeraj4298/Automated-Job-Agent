"""
browser/form_utils.py — Form field detection and ATS platform helpers.

Key capabilities:
  - detect_ats_platform()   : Identify which ATS the page is running
  - find_field()            : Fuzzy field locator by label/name/placeholder
  - human_type()            : Type text with realistic delays
  - scroll_to_element()     : Smooth scroll before interacting
  - detect_sensitive_fields(): Check for SSN / bank account fields
"""

import asyncio
import re
from typing import List, Optional

from loguru import logger
from playwright.async_api import Locator, Page

from browser.timing import mid_field_pause, type_delay


# ── ATS Platform Detection ─────────────────────────────────────────────────

ATS_SIGNATURES = {
    "workday": [
        "myworkdayjobs.com",
        "workday.com",
        "wd1.myworkdayjobs",
        "wd5.myworkdayjobs",
        "wd3.myworkdayjobs",
    ],
    "taleo": ["taleo.net", "tbe.taleo.net", "hire.tbe.taleo"],
    "icims": ["icims.com", "jobs.icims.com"],
    "greenhouse": ["boards.greenhouse.io", "greenhouse.io"],
    "lever": ["jobs.lever.co", "lever.co/"],
    "smartrecruiters": ["careers.smartrecruiters.com", "smartrecruiters.com"],
    "jobvite": ["jobs.jobvite.com", "jobvite.com"],
    "successfactors": ["successfactors.com", "sapsf.com"],
    "ashby": ["jobs.ashbyhq.com", "ashbyhq.com"],
}

SENSITIVE_FIELD_PATTERNS = re.compile(
    r"\b(ssn|social.?security|tax.?id|bank.?account|routing.?number"
    r"|ein|national.?id|passport.?number)\b",
    re.IGNORECASE,
)


def detect_ats_platform(url: str) -> str:
    """
    Inspect the URL to identify the ATS platform.
    Returns one of: workday | taleo | icims | greenhouse | lever |
                    smartrecruiters | jobvite | successfactors | ashby | generic
    """
    url_lower = url.lower()
    for platform, signatures in ATS_SIGNATURES.items():
        if any(sig in url_lower for sig in signatures):
            logger.debug(f"ATS detected: {platform}")
            return platform
    return "generic"


# ── Shared constants ────────────────────────────────────────────────────────
FORM_ELEMENT_TYPES = ["input", "textarea", "select", "button"]

SENSITIVE_FIELD_PATTERNS = re.compile(
    r"\b(ssn|social.?security|tax.?id|bank.?account|routing.?number"
    r"|ein|national.?id|passport.?number)\b",
    re.IGNORECASE,
)

# Generic examples only. Real candidate data must come from local runtime config.
FIELD_MAPPING = {
    # Name
    "name": "Example Candidate",
    "full name": "Example Candidate",
    "first name": "Example",
    "last name": "Candidate",
    "surname": "Candidate",
    
    # Contact
    "email": "candidate@example.com",
    "email id": "candidate@example.com",
    "phone": "+10000000000",
    "mobile": "+10000000000",
    "contact": "+10000000000",
    
    # Location
    "location": "Remote",
    "city": "Example City",
    "state": "Example State",
    "province": "Example Province",
    "country": "Example Country",
    "pincode": "000000",
    "zip": "000000",
    "postal": "000000",
    
    # Experience
    "current company": "Example Company",
    "employer": "Example Company",
    "current role": "Software Developer",
    "designation": "Software Developer",
    "experience": "1",
    "years": "1",
    "total experience": "1 year",
    "notice period": "30 days",
    
    # Education
    "degree": "B.Tech",
    "qualification": "B.Tech",
    "university": "Example University",
    "college": "Example College",
    "graduation year": "2024",
    "cgpa": "7.63",
    "gpa": "7.63",
    "percentage": "76.3",
    
    # Details & skills
    "skills": "Python, FastAPI, MongoDB, GCP, SQL, Tableau, Pandas",
    "key skills": "Python, FastAPI, MongoDB, GCP, SQL, Tableau, Pandas",
    "how did you hear": "Job Board",
    "are you authorized": "Yes",
    "require sponsorship": "No",
    "willing to relocate": "Yes",
    "gender": "Male",
    "resume": "upload",
    "cv": "upload",
    "references": "Available on request",
    "available from": "Immediately",
    "join date": "Immediately",
}

# ── Platform Detection ───────────────────────────────────────────────────

def detect_platform(url: str) -> str:
    """Returns the name of the ATS platform based on the URL."""
    url_lower = url.lower()
    
    if "docs.google.com/forms" in url_lower or "forms.gle/" in url_lower:
        return "Google Form"
    if "forms.office.com" in url_lower or "forms.microsoft.com" in url_lower:
        return "Microsoft Form"
    if "linkedin.com/jobs/" in url_lower:
        return "LinkedIn"
    if "boards.greenhouse.io" in url_lower:
        return "Greenhouse"
    if "jobs.lever.co" in url_lower:
        return "Lever"
    if ".myworkdayjobs.com" in url_lower:
        return "Workday"
    if "jobs.ashbyhq.com" in url_lower:
        return "Ashby"
    if "apply.workable.com" in url_lower:
        return "Workable"
    if "hire.withgoogle.com" in url_lower:
        return "Google Hire"
    if "careers.smartrecruiters.com" in url_lower:
        return "SmartRecruiters"
    if "icims.com" in url_lower:
        return "iCIMS"
    if "taleo.net" in url_lower:
        return "Taleo"
    if "bamboohr.com" in url_lower:
        return "BambooHR"
    if "jobvite.com" in url_lower:
        return "Jobvite"
    if "naukri.com/job-listings/" in url_lower or "naukri.com" in url_lower:
        return "Naukri"
    if "indeed.com/viewjob" in url_lower or "indeed.com/apply" in url_lower:
        return "Indeed"
        
    return "Generic"

# ── Field Locator ──────────────────────────────────────────────────────────

async def find_field(
    page: Page,
    hints: List[str],
    field_type: str = "input",
    timeout: int = 5000,
) -> Optional[Locator]:
    """
    Try to locate a form field by trying multiple selector strategies.
    `hints` is an ordered list of label texts, placeholder values, or name attrs.
    Returns the first visible, enabled locator found, or None.
    """
    strategies = []
    for hint in hints:
        h = hint.lower()
        strategies += [
            f"[name*='{h}']",
            f"[id*='{h}']",
            f"[placeholder*='{hint}']",
            f"[aria-label*='{hint}']",
            f"label:has-text('{hint}') ~ {field_type}",
            f"label:has-text('{hint}') + {field_type}",
        ]

    for selector in strategies:
        try:
            loc = page.locator(selector).first
            await loc.wait_for(state="visible", timeout=timeout)
            if await loc.is_enabled():
                return loc
        except Exception:
            continue
    return None


# ── Human-like Typing ──────────────────────────────────────────────────────

async def human_type(page: Page, selector_or_locator, text: str) -> None:
    """
    Type `text` into a field character-by-character with realistic delays.
    Accepts either a CSS selector string or a Playwright Locator.
    """
    if isinstance(selector_or_locator, str):
        element = page.locator(selector_or_locator).first
    else:
        element = selector_or_locator

    await element.click()
    await asyncio.sleep(0.2)

    for char in text:
        await element.type(char, delay=0)        # We manage delay ourselves
        delay = type_delay()
        pause = mid_field_pause()
        await asyncio.sleep(delay + pause)


# ── Smooth Scroll ─────────────────────────────────────────────────────────

async def scroll_to_element(page: Page, locator: Locator) -> None:
    """Scroll the element into view smoothly before interacting."""
    try:
        await locator.scroll_into_view_if_needed()
        await asyncio.sleep(0.3)
    except Exception as e:
        logger.debug(f"Scroll failed: {type(e).__name__}")


# ── Sensitive Field Detection ──────────────────────────────────────────────

async def detect_sensitive_fields(page: Page) -> List[str]:
    """
    Scan all visible input labels and placeholders for SSN / bank patterns.
    Returns a list of suspicious field identifiers (empty = safe).
    """
    suspicious: List[str] = []
    try:
        inputs = await page.query_selector_all("input, textarea, select")
        for el in inputs:
            for attr in ("name", "id", "placeholder", "aria-label"):
                val = await el.get_attribute(attr) or ""
                if SENSITIVE_FIELD_PATTERNS.search(val):
                    suspicious.append(f"{attr}={val}")
        # Also check visible label text
        labels = await page.query_selector_all("label")
        for label in labels:
            text = (await label.inner_text()).strip()
            if SENSITIVE_FIELD_PATTERNS.search(text):
                suspicious.append(f"label={text}")
    except Exception as e:
        logger.warning(f"Sensitive field scan error: {type(e).__name__}")
    return suspicious


# ── CAPTCHA Detection ──────────────────────────────────────────────────────

async def detect_captcha(page: Page) -> bool:
    """
    Return True if a CAPTCHA or bot-challenge element is visible on the page.
    Checks for common reCAPTCHA, hCaptcha, and Cloudflare challenge patterns.
    """
    captcha_selectors = [
        "iframe[src*='recaptcha']",
        "iframe[src*='hcaptcha']",
        ".g-recaptcha",
        "#cf-challenge-running",
        "[data-sitekey]",
        "div.h-captcha",
    ]
    for sel in captcha_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible():
                return True
        except Exception:
            continue
    return False


# ── MFA / 2FA Detection ────────────────────────────────────────────────────

async def detect_mfa(page: Page) -> bool:
    """
    Return True if a multi-factor authentication prompt is visible.
    Checks page title and common MFA form patterns.
    """
    mfa_keywords = ["verification code", "two-factor", "2fa", "authenticate",
                    "security code", "one-time password", "otp"]
    title = (await page.title()).lower()
    if any(kw in title for kw in mfa_keywords):
        return True
    content = (await page.content()).lower()
    return any(kw in content for kw in mfa_keywords[:4])  # Fast check
