"""Unit tests for trailing/atr.py — Wilder ATR over OHLC bars."""
from __future__ import annotations

import pytest
from trailing.atr import (
    true_range,
    compute_atr,
    refresh_atr_in_state,
    DEFAULT_REFRESH_SECONDS,
)


def _bar(h: float, l: float, c: float, o: float | None = None) -> dict:
    return {"open": o if o is not None else c, "high": h, "low": l, "close": c}


# ── true_range ──────────────────────────────────────────────────────────────


def test_true_range_within_bar():
    """When the bar fully contains prev_close, TR = high - low."""
    assert true_range(high=110, low=100, prev_close=105) == 10


def test_true_range_gap_up():
    """Gap up: |high - prev_close| dominates."""
    assert true_range(high=120, low=115, prev_close=100) == 20


def test_true_range_gap_down():
    """Gap down: |low - prev_close| dominates."""
    assert true_range(high=95, low=90, prev_close=110) == 20


# ── compute_atr ─────────────────────────────────────────────────────────────


def test_atr_returns_none_when_insufficient_bars():
    """period+1 bars needed (1 seed + N TRs); fewer → None."""
    bars = [_bar(100, 99, 99.5) for _ in range(5)]
    assert compute_atr(bars, period=14) is None


def test_atr_seed_is_simple_mean_of_first_n_trs():
    """First N TRs of a flat series have TR = high-low; ATR = that constant."""
    bars = [_bar(101, 99, 100) for _ in range(15)]  # 14+1 bars, TR=2 each
    atr = compute_atr(bars, period=14)
    assert atr == 2.0


def test_atr_increases_with_volatility():
    """A volatile series produces a larger ATR than a quiet one."""
    quiet = [_bar(100 + 0.1 * i, 99 + 0.1 * i, 99.5 + 0.1 * i) for i in range(20)]
    wild = [_bar(100 + 5 * i, 90 + 5 * i, 95 + 5 * i) for i in range(20)]
    assert compute_atr(wild, period=14) > compute_atr(quiet, period=14)


def test_atr_wilder_smoothing_responds_slowly():
    """After a long quiet period, one large bar moves ATR only modestly
    (Wilder's smoothing exponentially averages, not snaps)."""
    # 30 quiet bars (TR≈1) + 1 huge bar (TR=100)
    bars = [_bar(100.5, 99.5, 100) for _ in range(30)]
    bars.append(_bar(200, 100, 150))  # huge range bar
    atr = compute_atr(bars, period=14)
    # Pre-spike ATR is ~1.0; spike pushes it up but not to 100.
    assert 1.0 < atr < 20.0


def test_atr_invalid_period_raises():
    with pytest.raises(ValueError):
        compute_atr([_bar(1, 0, 0.5)] * 5, period=0)


# ── refresh_atr_in_state ────────────────────────────────────────────────────


def _flat_bars(n: int = 20, price: float = 100.0, range_: float = 2.0) -> list[dict]:
    return [
        {"open": price, "high": price + range_ / 2, "low": price - range_ / 2,
         "close": price}
        for _ in range(n)
    ]


def test_refresh_fetches_and_stores_atr_when_missing():
    state = {"symbol": "AAPL"}
    bars = _flat_bars(20, range_=2.0)
    refreshed = refresh_atr_in_state(state, fetch_bars=lambda s: bars, now=1000.0)
    assert refreshed is True
    assert state["atr"] == 2.0
    assert state["atr_refreshed_at"] == 1000.0


def test_refresh_skips_when_recent():
    state = {"symbol": "AAPL", "atr": 1.5, "atr_refreshed_at": 1000.0}
    called = []
    def fetch(sym):
        called.append(sym)
        return _flat_bars(20)
    # Only 1 minute later — well within max_age
    refreshed = refresh_atr_in_state(state, fetch_bars=fetch, now=1060.0)
    assert refreshed is False
    assert called == [], "Must not call fetch when ATR is fresh"
    assert state["atr"] == 1.5  # unchanged


def test_refresh_refetches_when_stale():
    state = {"symbol": "AAPL", "atr": 1.5, "atr_refreshed_at": 1000.0}
    # Past refresh window
    bars = _flat_bars(20, range_=5.0)
    refreshed = refresh_atr_in_state(
        state, fetch_bars=lambda s: bars,
        now=1000.0 + DEFAULT_REFRESH_SECONDS + 1,
    )
    assert refreshed is True
    assert state["atr"] == 5.0


def test_refresh_handles_empty_bars_gracefully():
    state = {"symbol": "AAPL"}
    refreshed = refresh_atr_in_state(state, fetch_bars=lambda s: [], now=1000.0)
    assert refreshed is False
    assert "atr" not in state


def test_refresh_returns_false_without_symbol():
    state = {}
    refreshed = refresh_atr_in_state(state, fetch_bars=lambda s: _flat_bars(20))
    assert refreshed is False


def test_atr_realistic_value_for_typical_stock():
    """Sanity check: a stock around $400 with $5-10 daily ranges yields ATR
    in single-digit dollars (not 0.0, not 100)."""
    import random
    random.seed(42)
    bars = []
    close = 400.0
    for _ in range(30):
        rng = random.uniform(5, 10)
        close += random.uniform(-3, 3)
        high = close + rng / 2
        low = close - rng / 2
        bars.append(_bar(high, low, close))
    atr = compute_atr(bars, period=14)
    assert 3.0 < atr < 15.0
