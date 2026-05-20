"""
browser/timing.py — Human-simulation delay functions.

All public functions return a float (seconds) that should be passed
to asyncio.sleep() or time.sleep().  Import the async helper
`sleep_human()` for convenience in async Playwright code.
"""

import asyncio
import random
import time

import numpy as np


# ── Per-character delay ────────────────────────────────────────────────────

def type_delay() -> float:
    """Per-character delay: 60–220 ms + Gaussian jitter.  Always positive."""
    base = random.uniform(0.06, 0.22)
    jitter = abs(np.random.normal(0, 0.03))
    return round(base + jitter, 4)


# ── Between form fields ────────────────────────────────────────────────────

def field_delay() -> float:
    """Pause between form fields: 300–2000 ms."""
    return round(random.uniform(0.3, 2.0), 3)


# ── Reading simulation ─────────────────────────────────────────────────────

def read_delay(word_count: int = 200) -> float:
    """
    Simulate a user reading the job description before applying.
    Base delay (3–12 s) plus proportional reading time at ~150 wpm.
    """
    base = random.uniform(3, 12)
    reading = (word_count / 150) * random.uniform(0.5, 2.5)
    return round(base + reading, 2)


# ── Pre-apply pause ────────────────────────────────────────────────────────

def pre_apply_delay() -> float:
    """Pause before clicking the Apply button: 2–8 s."""
    return round(random.uniform(2, 8), 2)


# ── Between applications ───────────────────────────────────────────────────

def between_applications() -> float:
    """
    Pause between completing one application and starting the next: 45–120 s.
    This is the most important cooldown for avoiding rate-limit detection.
    """
    return round(random.uniform(45, 120), 1)


# ── Domain bulk pause ──────────────────────────────────────────────────────

def domain_bulk_pause() -> float:
    """
    Every 5–8 applications on the same domain, pause for 4–12 min.
    Strongly mimics real browsing fatigue patterns.
    """
    return round(random.uniform(240, 720), 1)


# ── Session break ──────────────────────────────────────────────────────────

def session_break() -> float:
    """
    Every 15–20 applications or ~35 min, take a 12–25 min break.
    Avoids burst-detection heuristics used by LinkedIn and Indeed.
    """
    return round(random.uniform(720, 1500), 1)


# ── Mid-field pause ────────────────────────────────────────────────────────

def mid_field_pause() -> float:
    """
    Occasional pause while typing (simulates hesitation/thinking).
    15 % chance of 200–1200 ms, otherwise 0.
    """
    if random.random() < 0.15:
        return round(random.uniform(0.2, 1.2), 3)
    return 0.0


# ── Network navigation ─────────────────────────────────────────────────────

def page_load_buffer() -> float:
    """Extra buffer after page load event fires: 0.5–2.5 s."""
    return round(random.uniform(0.5, 2.5), 2)


def scroll_delay() -> float:
    """Delay between scroll steps: 80–300 ms."""
    return round(random.uniform(0.08, 0.30), 3)


# ── Async convenience helper ───────────────────────────────────────────────

async def async_sleep(seconds: float) -> None:
    """Await an asyncio sleep (convenience wrapper)."""
    await asyncio.sleep(seconds)


def sync_sleep(seconds: float) -> None:
    """Blocking sleep (for use in synchronous contexts)."""
    time.sleep(seconds)
