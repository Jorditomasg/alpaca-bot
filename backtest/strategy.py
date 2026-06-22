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

    def on_pub_date(self, date: str, new_filings: list[dict],
                    portfolio=None) -> list[Action]:
        # portfolio is accepted for a uniform strategy interface; baseline
        # ignores it (fixed notional, no equity-aware sizing).
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

    def on_pub_date(self, date: str, new_filings: list[dict],
                    portfolio=None) -> list[Action]:
        # portfolio accepted for interface uniformity; Improved uses fixed
        # notional, so it is ignored here (EquityFractionStrategy uses it).
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


# ── Equity-fraction (production sizing) ──────────────────────────────────────


class EquityFractionStrategy(ImprovedStrategy):
    """Improved signal/exit logic, but positions sized as a fraction of LIVE
    equity instead of a fixed dollar notional, with two concentration caps.

    This mirrors copy_trader/portfolio.py in production:
      - position_pct      : each buy targets this fraction of current equity
      - max_positions     : never hold more than N names at once
      - max_invested_pct  : never deploy more than this fraction of equity
                            (notional is clamped to the remaining room; a buy
                            with no room left is dropped)

    Fixed notional left most of the capital idle for normal-activity
    politicians (validated: ~2-7% deployed) while letting a hyperactive one
    over-concentrate. Equity-fraction + caps deploys capital and compounds the
    base, while the position cap is what keeps drawdown within tolerance.
    """

    name = "equity_fraction"

    def __init__(self, *args, position_pct: float = 0.05,
                 max_invested_pct: float = 0.80, max_positions: int = 8,
                 **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.position_pct = position_pct
        self.max_invested_pct = max_invested_pct
        self.max_positions = max_positions

    def on_pub_date(self, date: str, new_filings: list[dict],
                    portfolio=None, marks: dict[str, float] | None = None) -> list[Action]:
        # Reuse parent for filtering (freshness/min-amount/follow) and sells;
        # only buy sizing differs.
        base_actions = super().on_pub_date(date, new_filings)
        if portfolio is None:
            return base_actions

        # Mark-to-market equity when the engine supplies held-position prices;
        # falls back to cost-basis equity otherwise.
        equity = portfolio.equity(marks or {})
        invested = equity - portfolio.cash
        deploy_room = self.max_invested_pct * equity - invested
        held = set(portfolio.positions.keys())

        out: list[Action] = []
        for a in base_actions:
            if a.kind != "buy":
                out.append(a)
                continue
            if a.ticker in held:
                continue  # already open — engine would no-op anyway
            if len(held) >= self.max_positions:
                continue
            if deploy_room <= 0:
                continue
            notional = min(self.position_pct * equity, deploy_room)
            if notional < 1.0:
                continue
            out.append(Action(kind="buy", ticker=a.ticker,
                              notional=round(notional, 2), reason=a.reason))
            # Reserve against caps for the rest of this batch.
            held.add(a.ticker)
            deploy_room -= notional
        return out
