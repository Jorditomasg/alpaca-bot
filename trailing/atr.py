"""Average True Range — Wilder's smoothing method.

ATR adapts the trailing stop distance to the actual volatility of the
underlying. A fixed-percent trail (5%) tightens too much on a quiet stock
and loosens too much on a volatile one; ATR-based stops normalise across
instruments.

True Range for bar `i` (for i > 0):
    TR_i = max(
        high_i - low_i,
        |high_i - close_{i-1}|,
        |low_i  - close_{i-1}|
    )

ATR_n (Wilder) is the running smoothed mean of TR over n bars:
    ATR_n = ((n - 1) * ATR_{n-1} + TR_n) / n

Seed: ATR_n at index `period` is the simple mean of TR_1..TR_period.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Callable, Sequence

DEFAULT_PERIOD = 14
DEFAULT_REFRESH_SECONDS = 4 * 3600  # 4h — daily ATR doesn't move intraday


def true_range(high: float, low: float, prev_close: float) -> float:
    return max(
        high - low,
        abs(high - prev_close),
        abs(low - prev_close),
    )


def compute_atr(bars: Sequence[dict], period: int = 14) -> float | None:
    """Return Wilder-smoothed ATR over the given OHLC bars.

    Each bar dict must have 'high', 'low', 'close' keys. Bars are oldest-first.
    Returns None when there is not enough data (need at least period+1 bars).
    """
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    if len(bars) <= period:
        return None

    # First `period` true ranges (indices 1..period inclusive).
    trs = [
        true_range(
            bars[i]["high"],
            bars[i]["low"],
            bars[i - 1]["close"],
        )
        for i in range(1, period + 1)
    ]
    atr = sum(trs) / period

    # Wilder smoothing for the remaining bars.
    for i in range(period + 1, len(bars)):
        tr = true_range(
            bars[i]["high"],
            bars[i]["low"],
            bars[i - 1]["close"],
        )
        atr = ((period - 1) * atr + tr) / period

    return round(atr, 4)


def refresh_atr_in_state(
    state: dict,
    fetch_bars: Callable[[str], list[dict]],
    period: int = DEFAULT_PERIOD,
    max_age_seconds: int = DEFAULT_REFRESH_SECONDS,
    now: float | None = None,
) -> bool:
    """Refresh state['atr'] if cached value is missing or older than max_age.

    Returns True if a refresh happened. Caller handles persistence.
    `now` is injectable for tests; defaults to real wall clock.
    """
    current_ts = now if now is not None else datetime.now(timezone.utc).timestamp()
    last_refresh = state.get("atr_refreshed_at") or 0
    has_atr = state.get("atr") is not None
    if has_atr and (current_ts - last_refresh) < max_age_seconds:
        return False

    symbol = state.get("symbol")
    if not symbol:
        return False

    bars = fetch_bars(symbol)
    atr = compute_atr(bars, period=period)
    if atr is None:
        return False

    state["atr"] = atr
    state["atr_refreshed_at"] = current_ts
    return True
