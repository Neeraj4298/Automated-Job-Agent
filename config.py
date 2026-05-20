"""
config.py — Central configuration loader.
Reads from .env file and validates all settings using Pydantic.
Import `settings` anywhere in the codebase to access config values.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Identity ─────────────────────────────────────────────────────
    full_name: str
    email: str
    phone: str
    location: str
    linkedin_url: str = ""
    github_url: str = ""
    resume_path: Path

    # ── Credentials  ─────────────────────────────────────────────────
    # Raw JSON string from .env; parsed below
    credentials: str = "{}"

    # ── Job Preferences ───────────────────────────────────────────────
    roles: str  # comma-separated string from .env
    experience_range: str = "1-2 years"
    daily_max_applications: int = 50
    location_filter: str = "remote"
    allow_contract: bool = False
    allow_internship: bool = False
    per_domain_daily_limit: int = 10

    # ── AI — Google Gemini (primary) ────────────────────────────────
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-pro"

    # ── AI — Fallbacks ────────────────────────────────────────────────
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    openai_model: str = "gpt-4o"

    # ── Search ───────────────────────────────────────────────────────
    serpapi_key: str = ""

    # ── Alerts ───────────────────────────────────────────────────────
    alert_email: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── Browser ───────────────────────────────────────────────────────
    headless: bool = True
    db_path: str = "applied_jobs.db"

    # ── Debug ─────────────────────────────────────────────────────────
    debug_mode: bool = False

    # ── Extended Profile (for cover letters & screening) ─────────────
    skills_summary: str = ""
    achievements: str = ""
    work_authorization: str = "Authorized to work"
    salary_expectation: str = "Negotiable"
    willing_to_relocate: bool = False
    available_start_date: str = "Immediately"

    # ── Parsed/Derived (populated by validators) ──────────────────────
    roles_list: List[str] = []
    credentials_dict: Dict[str, Dict[str, str]] = {}

    @field_validator("resume_path", mode="before")
    @classmethod
    def validate_resume_path(cls, v):
        p = Path(v)
        if not p.exists():
            raise ValueError(
                f"RESUME_PATH does not exist: {v}. "
                "Please set an absolute path to your resume PDF in .env"
            )
        return p

    @model_validator(mode="after")
    def parse_derived_fields(self):
        # Parse roles list
        self.roles_list = [r.strip() for r in self.roles.split(",") if r.strip()]

        # Parse credentials JSON
        try:
            self.credentials_dict = json.loads(self.credentials)
        except json.JSONDecodeError as e:
            raise ValueError(f"CREDENTIALS env var is not valid JSON: {e}")

        return self

    def get_credentials(self, domain: str) -> Optional[Dict[str, str]]:
        """Return credentials for a given domain, or None if not configured."""
        return self.credentials_dict.get(domain)

    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    def has_serpapi(self) -> bool:
        return bool(self.serpapi_key)

    def has_telegram(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    def has_email_alerts(self) -> bool:
        return bool(self.alert_email and self.smtp_user and self.smtp_pass)


# Global singleton — import this everywhere
settings = Settings()
