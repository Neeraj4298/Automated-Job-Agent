"""
ai/keyword_extract.py — Keyword extraction combining TF-IDF and LLM approaches.

  extract_keywords_tfidf(text)  → offline, fast (no API call)
  extract_keywords_llm(text)    → LLM-based (higher quality)
  extract_keywords(text)        → merges both, deduplicates
"""

import re
from typing import List, Optional

from loguru import logger


# ── TF-IDF based extraction (no API cost) ─────────────────────────────────

STOP_WORDS_EXTRA = {
    "experience", "years", "team", "work", "role", "position", "including",
    "required", "preferred", "ability", "strong", "excellent", "knowledge",
    "looking", "opportunity", "candidate", "join", "environment", "skills",
    "please", "apply", "company", "working", "using", "responsible",
    "will", "must", "also", "good", "well", "provide", "ensure",
}


def extract_keywords_tfidf(text: str, top_n: int = 10) -> List[str]:
    """
    Extract top N keywords using scikit-learn TF-IDF on a corpus of one doc.
    Falls back to frequency-based extraction if sklearn is unavailable.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        import numpy as np

        vectorizer = TfidfVectorizer(
            stop_words="english",
            max_features=200,
            ngram_range=(1, 2),        # Unigrams + bigrams
            min_df=1,
        )
        tfidf_matrix = vectorizer.fit_transform([text])
        feature_names = vectorizer.get_feature_names_out()
        scores = tfidf_matrix.toarray()[0]
        top_indices = np.argsort(scores)[::-1][:top_n * 3]   # Get more, then filter

        keywords = []
        for idx in top_indices:
            kw = feature_names[idx].strip()
            if kw not in STOP_WORDS_EXTRA and len(kw) > 2:
                keywords.append(kw)
            if len(keywords) >= top_n:
                break
        return keywords

    except ImportError:
        logger.warning("scikit-learn not installed. Using fallback keyword extraction.")
        return _frequency_fallback(text, top_n)


def _frequency_fallback(text: str, top_n: int = 10) -> List[str]:
    """Simple word-frequency fallback when sklearn is unavailable."""
    from collections import Counter
    words = re.findall(r"\b[a-zA-Z][a-zA-Z+#.]{2,}\b", text.lower())
    filtered = [w for w in words if w not in STOP_WORDS_EXTRA]
    counter = Counter(filtered)
    return [w for w, _ in counter.most_common(top_n)]


# ── LLM based extraction ───────────────────────────────────────────────────

def extract_keywords_llm(text: str) -> Optional[List[str]]:
    """
    Use Claude/GPT to extract keywords with role family and seniority detection.
    Returns list of keywords, or None if AI call fails.
    """
    try:
        from ai.llm_client import LLMClient
        client = LLMClient()
        result = client.call("keyword_extract", job_description=text)
        if result and "top_keywords" in result:
            return result["top_keywords"]
    except Exception as e:
        logger.warning(f"LLM keyword extraction failed: {type(e).__name__}")
    return None


# ── Combined extraction ────────────────────────────────────────────────────

def extract_keywords(text: str, top_n: int = 10) -> List[str]:
    """
    Merge TF-IDF and LLM keywords, deduplicate, and return top N.
    LLM results take priority (listed first after dedup).
    """
    tfidf_kws = extract_keywords_tfidf(text, top_n=top_n)
    llm_kws = extract_keywords_llm(text) or []

    seen = set()
    merged = []
    for kw in llm_kws + tfidf_kws:
        kw_lower = kw.lower()
        if kw_lower not in seen:
            seen.add(kw_lower)
            merged.append(kw)
        if len(merged) >= top_n:
            break

    logger.debug(f"Keywords extracted: {merged}")
    return merged
