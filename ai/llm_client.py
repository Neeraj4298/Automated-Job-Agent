"""
ai/llm_client.py — Google Gemini (primary) + Anthropic + OpenAI wrapper.

Priority order:
  1. Google Gemini 2.5 Pro   (GEMINI_API_KEY)
  2. Anthropic Claude        (ANTHROPIC_API_KEY)
  3. OpenAI GPT              (OPENAI_API_KEY)

All calls return a parsed Python dict from the structured JSON response.
"""

import json
import re as _re
from typing import Any, Dict, Optional

from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ai.prompts import (
    cover_letter_prompt,
    keyword_extract_prompt,
    qualify_prompt,
    screening_prompt,
)

# Lazy client singletons
_gemini_client = None
_anthropic_client = None
_openai_client = None


def _get_gemini():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        from config import settings
        genai.configure(api_key=settings.gemini_api_key)
        _gemini_client = genai
    return _gemini_client


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic as ant
        from config import settings
        _anthropic_client = ant.Anthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


def _get_openai():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        from config import settings
        _openai_client = OpenAI(api_key=settings.openai_api_key)
    return _openai_client


TASK_PROMPT_MAP = {
    "qualify": qualify_prompt,
    "cover_letter": cover_letter_prompt,
    "screening": screening_prompt,
    "keyword_extract": keyword_extract_prompt,
}


class LLMClient:
    """
    Unified LLM client with Gemini → Anthropic → OpenAI fallback chain.
    All calls return a parsed Python dict from the structured JSON response.
    """

    def __init__(self):
        from config import settings
        self.settings = settings
        self._token_usage: Dict[str, int] = {"input": 0, "output": 0}

    def call(self, task_type: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Make an LLM call for the given task type.

        task_type: "qualify" | "cover_letter" | "screening" | "keyword_extract"
        kwargs: passed to the corresponding prompt builder function.

        Returns a dict parsed from the JSON response, or None on failure.
        """
        if task_type not in TASK_PROMPT_MAP:
            raise ValueError(f"Unknown task type: {task_type}")

        prompt_fn = TASK_PROMPT_MAP[task_type]
        system_prompt, user_prompt = prompt_fn(**kwargs)

        # ── Priority 1: OpenAI GPT ─────────────────────────────────────
        if self.settings.has_openai():
            return self._call_openai(system_prompt, user_prompt)

        # ── Priority 2: Google Gemini ──────────────────────────────────
        if self.settings.has_gemini():
            logger.warning("OpenAI unavailable. Trying Gemini fallback.")
            result = self._call_gemini(system_prompt, user_prompt)
            if result is not None:
                return result

        # ── Priority 3: Anthropic Claude ───────────────────────────────
        if self.settings.has_anthropic():
            logger.warning("Gemini unavailable. Trying Anthropic fallback.")
            result = self._call_anthropic(system_prompt, user_prompt)
            if result is not None:
                return result

        logger.error("No AI provider available. Set OPENAI_API_KEY in .env")
        return None

    # ── Google Gemini ──────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=False,
    )
    def _call_gemini(
        self, system_prompt: str, user_prompt: str
    ) -> Optional[Dict[str, Any]]:
        """Call Google Gemini and return parsed JSON dict."""
        try:
            from google.generativeai import GenerativeModel
            model = GenerativeModel(
                self.settings.gemini_model,
                system_instruction=system_prompt,
            )
            response = model.generate_content(
                user_prompt,
                generation_config={"response_mime_type": "application/json"},
            )
            text = response.text
            if not text:
                logger.error(f"Gemini returned empty text. Raw: {response}")
                raise ValueError("Empty response from Gemini")
            
            usage = response.usage_metadata
            if usage:
                self._token_usage["input"] += usage.prompt_token_count
                self._token_usage["output"] += usage.candidates_token_count

            logger.debug(f"Gemini response ({len(text)} chars): {text[:120]}…")
            return self._parse_json(text)
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise

    # ── Anthropic Claude ───────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=False,
    )
    def _call_anthropic(
        self, system_prompt: str, user_prompt: str
    ) -> Optional[Dict[str, Any]]:
        """Call Anthropic Claude and return parsed JSON dict."""
        try:
            client = _get_anthropic()
            response = client.messages.create(
                model=self.settings.anthropic_model,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = response.content[0].text.strip()
            self._token_usage["input"] += response.usage.input_tokens
            self._token_usage["output"] += response.usage.output_tokens
            return self._parse_json(text)
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            raise

    # ── OpenAI GPT ─────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=False,
    )
    def _call_openai(
        self, system_prompt: str, user_prompt: str
    ) -> Optional[Dict[str, Any]]:
        """Call OpenAI GPT and return parsed JSON dict."""
        try:
            client = _get_openai()
            response = client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=1024,
            )
            text = response.choices[0].message.content.strip()
            usage = response.usage
            if usage:
                self._token_usage["input"] += usage.prompt_tokens
                self._token_usage["output"] += usage.completion_tokens
            return self._parse_json(text)
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise

    # ── JSON parsing ───────────────────────────────────────────────────

    @staticmethod
    def _parse_json(text: str) -> Optional[Dict[str, Any]]:
        """Extract and parse JSON from LLM response text."""
        # Strip markdown code fences: ```json ... ``` or ``` ... ```
        if "```" in text:
            fenced = _re.sub(r"```(?:json|python)?\s*\n?", "", text)
            fenced = fenced.replace("```", "").strip()
            text = fenced if fenced.strip() else text
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error from LLM response: {e}\nRaw: {text[:200]}")
            return None

    @property
    def token_usage(self) -> Dict[str, int]:
        """Return cumulative token usage for this client instance."""
        return dict(self._token_usage)
