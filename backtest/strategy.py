"""Strategy implementations for backtesting.

Two variants:
  BaselineStrategy — mirrors current production logic. Buy when followed
    politician buys; sell only when they sell. No exits on PnL or time.
  ImprovedStrategy — adds pub_date freshness filter, min-amount filter,
    hybrid exits (hard stop / trailing / max-holding), amount-weighted scoring.

Both yield Action objects to the engine, which applies them to the portfolio.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from backtest.portfolio import SimulatedPortfolio


@dataclass
class Action:
    kind: Literal["buy", "sell"]
    ticker: str
    notional: float = 0.0
    reason: str = ""


# ── Baseline ────────────────────────────────────────────────────────────────


class BaselineStrategy:
    name = "baseline"

    def __init__(self, starting_cash: float, notional_per_trade: float) -> None:
        self.starting_cash = starting_cash
        self.notional_per_trade = notional_per_trade
        self._following: str | None = None

    def set_following(self, politician: str) -> None:
        self._following = politician

    def on_pub_date(self, date: str, new_filings: list[dict]) -> list[Action]:
        if not self._following:
            return []
        actions: list[Action] = []
        for f in new_filings:
            if f["politician"].lower() != self._following.lower():
                continue
            if f["type"] == "buy":
                actions.append(Action(kind="buy", ticker=f["ticker"],
                                       notional=self.notional_per_trade,
                                       reason="politician_buy"))
            elif f["type"] == "sell":
                actions.append(Action(kind="sell", ticker=f["ticker"],
                                       reason="politician_sell"))
        return actions

    def check_exits(
        self, date: str, portfolio: SimulatedPortfolio, current_prices: dict[str, float]
    ) -> list[Action]:
        return []


# ── Improved ────────────────────────────────────────────────────────────────


class ImprovedStrategy:
    name = "improved"

    def __init__(
        self,
        starting_cash: float,
        notional_per_trade: float,
        pub_freshness_days: int = 7,
        min_amount: int = 15000,
        stop_loss_pct: float = 8.0,
        trail_arm_pct: float = 8.0,
        trail_giveback_pct: float = 5.0,
        max_holding_days: int = 90,
    ) -> None:
        self.starting_cash = starting_cash
        self.notional_per_trade = notional_per_trade
        self.pub_freshness_days = pub_freshness_days
        self.min_amount = min_amount
        self.stop_loss_pct = stop_loss_pct
        self.trail_arm_pct = trail_arm_pct
        self.trail_giveback_pct = trail_giveback_pct
        self.max_holding_days = max_holding_days
        self._following: str | None = None

    def set_following(self, politician: str) -> None:
        self._following = politician

    def on_pub_date(self, date: str, new_filings: list[dict]) -> list[Action]:
        if not self._following:
            return []
        today = datetime.strptime(date, "%Y-%m-%d")
        actions: list[Action] = []

        for f in new_filings:
            if f["politician"].lower() != self._following.lower():
                continue

            # Freshness filter — only act on filings published within window
            pub = datetime.strptime(f["pub_date"], "%Y-%m-%d")
            age_days = (today - pub).days
            if age_days > self.pub_freshness_days:
                continue

            # Size filter — high-conviction trades only
            if f.get("amount_mid", 0) < self.min_amount:
                continue

            if f["type"] == "buy":
                actions.append(Action(kind="buy", ticker=f["ticker"],
                                       notional=self.notional_per_trade,
                                       reason="politician_buy_filtered"))
            elif f["type"] == "sell":
                actions.append(Action(kind="sell", ticker=f["ticker"],
                                       reason="politician_sell"))
        return actions

    def check_exits(
        self, date: str, portfolio: SimulatedPortfolio, current_prices: dict[str, float]
    ) -> list[Action]:
        today = datetime.strptime(date, "%Y-%m-%d")
        actions: list[Action] = []

        for ticker, pos in list(portfolio.positions.items()):
            price = current_prices.get(ticker)
            if price is None:
                continue

            # Update high watermark for trailing logic
            if price > pos.high_watermark:
                pos.high_watermark = price

            # Hard stop loss from cost basis
            drawdown_pct = (price / pos.cost_basis - 1.0) * 100.0
            if drawdown_pct <= -self.stop_loss_pct:
                actions.append(Action(kind="sell", ticker=ticker, reason="stop_loss"))
                continue

            # Trailing stop — armed once peak gain crosses trail_arm_pct
            peak_gain_pct = (pos.high_watermark / pos.cost_basis - 1.0) * 100.0
            if peak_gain_pct >= self.trail_arm_pct:
                floor = pos.high_watermark * (1.0 - self.trail_giveback_pct / 100.0)
                if price < floor:
                    actions.append(Action(kind="sell", ticker=ticker, reason="trailing_stop"))
                    continue

            # Max holding period — signal decays after this
            entry = datetime.strptime(pos.entry_date, "%Y-%m-%d")
            holding_days = (today - entry).days
            if holding_days >= self.max_holding_days:
                actions.append(Action(kind="sell", ticker=ticker, reason="signal_expired"))

        return actions
