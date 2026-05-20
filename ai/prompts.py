"""
ai/prompts.py — Structured prompt builders for all AI task types.

Each function returns a (system_prompt, user_prompt) tuple.
The system prompt enforces deterministic JSON-only output.
"""

from typing import Dict, List

# ── System Prompt ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a deterministic job application agent. You make structured decisions and produce structured outputs. You never improvise.

RULES:
- Output ONLY valid JSON. No prose, no markdown, no explanation.
- If uncertain about any field → set value to null, set "flag": true, and set "reason": "<why>".
- Never fabricate experience or credentials.
- Never produce output that contradicts the user's actual profile.
- If a task is outside your defined scope → return:
  {"action": "halt", "reason": "<description>", "alert": true}"""


# ── QUALIFY ────────────────────────────────────────────────────────────────

def qualify_prompt(job_description: str, user_profile: Dict) -> tuple[str, str]:
    """
    Determine whether this job matches the user's profile and preferences.
    Returns the system prompt and user prompt as a tuple.
    """
    user_prompt = f"""Evaluate this job for the candidate. Return ONLY JSON in this exact schema:
{{
  "pass": true|false,
  "reason": "string",
  "experience_required": "string",
  "role_match": true|false,
  "type_match": true|false,
  "flag": false
}}

CANDIDATE PROFILE:
Name: {user_profile.get('full_name', '')}
Target Roles: {', '.join(user_profile.get('roles', []))}
Experience Range: {user_profile.get('experience_range', '1-2 years')}
Location Preference: {user_profile.get('location_filter', 'remote')}
Allow Contract: {user_profile.get('allow_contract', False)}
Allow Internship: {user_profile.get('allow_internship', False)}

JOB DESCRIPTION:
{job_description[:4000]}

QUALIFICATION RULES:
- pass=true ONLY if: role_match=true AND type_match=true AND experience_required ≤ 3 years
- role_match=true if job title roughly matches one of the candidate's target roles
- type_match=true if job type (full-time/contract/internship) is acceptable to the candidate
- If job requires >3 years experience: pass=false, reason explains this
- If SSN, security clearance, or citizenship required: pass=false, flag=true"""

    return SYSTEM_PROMPT, user_prompt


# ── COVER LETTER ───────────────────────────────────────────────────────────

def cover_letter_prompt(
    job_description: str,
    user_profile: Dict,
    keywords: List[str],
) -> tuple[str, str]:
    """Generate a short, targeted cover letter (≤300 chars)."""
    user_prompt = f"""Write a cover letter snippet for this job application. Return ONLY JSON:
{{
  "text": "string (≤300 chars, 1-3 sentences)",
  "keywords_matched": ["skill1","skill2"],
  "company_signal_used": "string|null",
  "flag": false
}}

CANDIDATE PROFILE:
Name: {user_profile.get('full_name', '')}
LinkedIn: {user_profile.get('linkedin_url', '')}
GitHub: {user_profile.get('github_url', '')}
Skills & Experience: {user_profile.get('skills_summary', 'See resume')}
Achievements: {user_profile.get('achievements', '')}

TOP KEYWORDS FROM JOB:
{', '.join(keywords[:10])}

JOB DESCRIPTION:
{job_description[:3000]}

RULES:
- text must be ≤300 characters (hard limit)
- Use specific numbers/metrics from achievements if available
- Reference one specific thing from the JD (company signal)
- NEVER fabricate experience or skills not in the profile
- keywords_matched = which of the top keywords appear in the generated text"""

    return SYSTEM_PROMPT, user_prompt


# ── SCREENING ──────────────────────────────────────────────────────────────

def screening_prompt(
    questions: List[str],
    user_profile: Dict,
) -> tuple[str, str]:
    """Map screening questions to appropriate answers from the user's profile."""
    questions_block = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))

    user_prompt = f"""Answer these application screening questions. Return ONLY JSON:
{{
  "answers": {{
    "question_verbatim": "answer"
  }},
  "unmapped_questions": ["question1"],
  "flag": true|false,
  "reason": "string|null"
}}

CANDIDATE PROFILE:
Name: {user_profile.get('full_name', '')}
Email: {user_profile.get('email', '')}
Phone: {user_profile.get('phone', '')}
Location: {user_profile.get('location', '')}
LinkedIn: {user_profile.get('linkedin_url', '')}
Experience Range: {user_profile.get('experience_range', '1-2 years')}
Skills: {user_profile.get('skills_summary', '')}
Visa/Work Auth: {user_profile.get('work_authorization', 'Authorized to work in the US')}
    Salary Expectation: {user_profile.get('salary_expectation', 'Negotiable')}
    Saved Answers to Past Questions: {user_profile.get('saved_answers', {})}

    SCREENING QUESTIONS:
{questions_block}

RULES:
- Answer each question using ONLY information from the profile above
- Relocation questions: always answer "Yes"
- Yes/No questions: answer "Yes" or "No" exactly
- Salary questions: use salary_expectation if provided
- Questions you cannot answer from profile: DO NOT GUESS OR ASSUME. add to unmapped_questions, set flag=true
- NEVER fabricate information not in the profile
- For work authorization questions: always answer truthfully"""

    return SYSTEM_PROMPT, user_prompt


# ── KEYWORD EXTRACT ────────────────────────────────────────────────────────

def keyword_extract_prompt(job_description: str) -> tuple[str, str]:
    """Extract top keywords and metadata from a job description."""
    user_prompt = f"""Analyze this job description and extract key information. Return ONLY JSON:
{{
  "top_keywords": ["kw1","kw2","kw3","kw4","kw5"],
  "role_family": "string",
  "seniority_signal": "junior|mid|senior|unclear",
  "experience_range_found": "string|null"
}}

JOB DESCRIPTION:
{job_description[:4000]}

RULES:
- top_keywords: 5–10 most important technical skills and tools mentioned
- role_family: broad category, e.g. "Software Engineering", "Data Science", "Product Management"
- seniority_signal: infer from title and language (junior=0-2yr, mid=2-5yr, senior=5+yr)
- experience_range_found: exact string from JD like "3-5 years" or null if not stated"""

    return SYSTEM_PROMPT, user_prompt
