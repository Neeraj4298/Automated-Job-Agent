"""
tests/test_ai_prompts.py — Tests for AI prompt builders and LLM client parsing.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from ai.prompts import (
    SYSTEM_PROMPT,
    qualify_prompt,
    cover_letter_prompt,
    screening_prompt,
    keyword_extract_prompt,
)


SAMPLE_JD = """
We are looking for a Software Developer I to join our team.
Requirements: 1-2 years of experience with Python, SQL, and REST APIs.
Full-time, remote friendly role. Competitive salary.
"""

SAMPLE_PROFILE = {
    "full_name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "+1-555-0000",
    "location": "Remote",
    "linkedin_url": "https://linkedin.com/in/janedoe",
    "github_url": "https://github.com/janedoe",
    "roles": ["Software Developer I", "Data Analyst"],
    "experience_range": "1-2 years",
    "location_filter": "remote",
    "allow_contract": False,
    "allow_internship": False,
    "skills_summary": "Python, SQL, REST APIs, machine learning",
    "achievements": "Built an API that reduced load time by 40%",
}


# ── System prompt ──────────────────────────────────────────────────────────

def test_system_prompt_is_non_empty():
    assert len(SYSTEM_PROMPT) > 50


def test_system_prompt_enforces_json_output():
    assert "JSON" in SYSTEM_PROMPT or "json" in SYSTEM_PROMPT.lower()


# ── qualify_prompt ─────────────────────────────────────────────────────────

def test_qualify_prompt_returns_tuple():
    sys_p, user_p = qualify_prompt(SAMPLE_JD, SAMPLE_PROFILE)
    assert isinstance(sys_p, str) and isinstance(user_p, str)


def test_qualify_prompt_contains_schema_keys():
    _, user_p = qualify_prompt(SAMPLE_JD, SAMPLE_PROFILE)
    for key in ("pass", "reason", "role_match", "experience_required"):
        assert key in user_p


def test_qualify_prompt_includes_job_description():
    _, user_p = qualify_prompt(SAMPLE_JD, SAMPLE_PROFILE)
    assert "Software Developer" in user_p or "Python" in user_p


# ── cover_letter_prompt ────────────────────────────────────────────────────

def test_cover_letter_prompt_returns_tuple():
    sys_p, user_p = cover_letter_prompt(SAMPLE_JD, SAMPLE_PROFILE, ["Python", "SQL"])
    assert isinstance(sys_p, str) and isinstance(user_p, str)


def test_cover_letter_mentions_char_limit():
    _, user_p = cover_letter_prompt(SAMPLE_JD, SAMPLE_PROFILE, ["Python"])
    assert "300" in user_p


def test_cover_letter_includes_keywords():
    _, user_p = cover_letter_prompt(SAMPLE_JD, SAMPLE_PROFILE, ["Python", "SQL"])
    assert "Python" in user_p


# ── screening_prompt ───────────────────────────────────────────────────────

def test_screening_prompt_returns_tuple():
    questions = ["Are you authorized to work in the US?", "What is your salary expectation?"]
    sys_p, user_p = screening_prompt(questions, SAMPLE_PROFILE)
    assert isinstance(sys_p, str) and isinstance(user_p, str)


def test_screening_prompt_contains_questions():
    questions = ["How many years of Python experience do you have?"]
    _, user_p = screening_prompt(questions, SAMPLE_PROFILE)
    assert "Python" in user_p


def test_screening_prompt_contains_schema():
    _, user_p = screening_prompt(["Any question?"], SAMPLE_PROFILE)
    assert "unmapped_questions" in user_p


# ── keyword_extract_prompt ─────────────────────────────────────────────────

def test_keyword_extract_prompt_returns_tuple():
    sys_p, user_p = keyword_extract_prompt(SAMPLE_JD)
    assert isinstance(sys_p, str) and isinstance(user_p, str)


def test_keyword_extract_schema_present():
    _, user_p = keyword_extract_prompt(SAMPLE_JD)
    for key in ("top_keywords", "role_family", "seniority_signal", "experience_range_found"):
        assert key in user_p


# ── LLM client JSON parsing ────────────────────────────────────────────────

def test_parse_json_clean():
    from ai.llm_client import LLMClient
    client = LLMClient.__new__(LLMClient)  # Skip __init__ to avoid loading config
    result = client._parse_json('{"pass": true, "reason": "ok"}')
    assert result == {"pass": True, "reason": "ok"}


def test_parse_json_strips_markdown_fences():
    from ai.llm_client import LLMClient
    client = LLMClient.__new__(LLMClient)
    result = client._parse_json('```json\n{"flag": false}\n```')
    assert result is not None
    assert result.get("flag") is False


def test_parse_json_returns_none_on_invalid():
    from ai.llm_client import LLMClient
    client = LLMClient.__new__(LLMClient)
    result = client._parse_json("This is not JSON at all, sorry!")
    assert result is None
