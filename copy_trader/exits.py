"""Per-position exit policy for copied trades.

Pure function: given current positions + prices + today, decide which tickers
to close and why. The scheduler executes the decisions; this module is testable
in isolation.

Three exit triggers (first match wins, in priority order):
  1. stop_loss      — price has fallen `stop_loss_pct` from cost basis
  2. trailing_stop  — peak gain crossed `trail_arm_pct`, then price gave back
                      `trail_giveback_pct` from high watermark
  3. signal_expired — held for `max_holding_days` days (politician alpha decays)

Side-effect: advances `high_watermark` in-place when a new high is seen so
subsequent calls trail correctly.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ExitDecision:
    ticker: str
    reason: str  # "stop_loss" | "trailing_stop" | "signal_expired"


def evaluate(
    positions: dict[str, dict],
    prices: dict[str, float],
    *,
    today: str,
    stop_loss_pct: float,
    trail_arm_pct: float,
    trail_giveback_pct: float,
    max_holding_days: int,
) -> list[ExitDecision]:
    today_dt = datetime.strptime(today, "%Y-%m-%d")
    out: list[ExitDecision] = []

    for ticker, pos in positions.items():
        price = prices.get(ticker)
        if price is None or price <= 0:
            continue

        cost_basis = pos.get("cost_basis")
        entry_date = pos.get("entry_date")
        if cost_basis is None or entry_date is None or cost_basis <= 0:
            continue

        # Advance high watermark if needed
        hwm = pos.get("high_watermark", cost_basis)
        if price > hwm:
            pos["high_watermark"] = price
            hwm = price

        # 1. Hard stop loss from cost basis
        drawdown_pct = (price / cost_basis - 1.0) * 100.0
        if drawdown_pct <= -stop_loss_pct:
            out.append(ExitDecision(ticker=ticker, reason="stop_loss"))
            continue

        # 2. Trailing stop — only armed once HWM crosses trail_arm_pct
        peak_gain_pct = (hwm / cost_basis - 1.0) * 100.0
        if peak_gain_pct >= trail_arm_pct:
            floor = hwm * (1.0 - trail_giveback_pct / 100.0)
            if price < floor:
                out.append(ExitDecision(ticker=ticker, reason="trailing_stop"))
                continue

        # 3. Max holding period — signal has decayed
        try:
            entry_dt = datetime.strptime(entry_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        if (today_dt - entry_dt).days >= max_holding_days:
            out.append(ExitDecision(ticker=ticker, reason="signal_expired"))

    return out
