"""
tests/test_timing.py — Tests for browser timing functions.
"""

import pytest
from browser.timing import (
    type_delay,
    field_delay,
    read_delay,
    pre_apply_delay,
    between_applications,
    domain_bulk_pause,
    session_break,
    mid_field_pause,
    page_load_buffer,
    scroll_delay,
)

N = 200   # samples per function


def test_type_delay_within_range():
    values = [type_delay() for _ in range(N)]
    # Base max: 0.22 + Gaussian jitter (3σ ≈ 0.09) → allow up to 0.35
    assert all(0.06 <= v <= 0.35 for v in values), \
        f"Out of range: {[v for v in values if not (0.06 <= v <= 0.35)][:5]}"


def test_field_delay_within_range():
    values = [field_delay() for _ in range(N)]
    assert all(0.3 <= v <= 2.0 for v in values)


def test_read_delay_within_reasonable_range():
    # 300 words → base(3-12) + reading(1-5) = [4, 17]
    values = [read_delay(300) for _ in range(N)]
    assert all(3 <= v <= 25 for v in values)


def test_pre_apply_delay():
    values = [pre_apply_delay() for _ in range(N)]
    assert all(2.0 <= v <= 8.0 for v in values)


def test_between_applications():
    values = [between_applications() for _ in range(N)]
    assert all(45 <= v <= 120 for v in values)


def test_domain_bulk_pause():
    values = [domain_bulk_pause() for _ in range(N)]
    assert all(240 <= v <= 720 for v in values)


def test_session_break():
    values = [session_break() for _ in range(N)]
    assert all(720 <= v <= 1500 for v in values)


def test_mid_field_pause_mostly_zero():
    values = [mid_field_pause() for _ in range(N)]
    zeros = sum(1 for v in values if v == 0.0)
    # Should be ~85% zeros; allow 65-99% due to randomness
    assert 0.65 <= zeros / N <= 0.99, f"Zero ratio: {zeros/N:.2f}"


def test_mid_field_pause_nonzero_in_range():
    non_zero = [mid_field_pause() for _ in range(N * 10) if mid_field_pause() > 0]
    # Only check values that are actually non-zero
    nonzero = [v for v in [mid_field_pause() for _ in range(N * 5)] if v > 0]
    assert all(0.2 <= v <= 1.2 for v in nonzero)


def test_page_load_buffer():
    values = [page_load_buffer() for _ in range(N)]
    assert all(0.5 <= v <= 2.5 for v in values)


def test_scroll_delay():
    values = [scroll_delay() for _ in range(N)]
    assert all(0.08 <= v <= 0.30 for v in values)


def test_all_delays_are_positive():
    fns = [type_delay, field_delay, pre_apply_delay, between_applications,
           domain_bulk_pause, session_break, page_load_buffer, scroll_delay]
    for fn in fns:
        values = [fn() for _ in range(50)]
        assert all(v >= 0 for v in values), f"{fn.__name__} returned negative value"
