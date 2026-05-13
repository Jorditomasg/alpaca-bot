"""Backtest replay engine.

Drives the simulation forward one trading day at a time.

On each day:
  1. Mark portfolio to market using available closes.
  2. Pass open positions + closes to `strategy.check_exits` → execute sells.
  3. Find filings whose pub_date == today → pass to `strategy.on_pub_date`
     → execute buys/sells using today's close as fill price.
  4. Record equity for the day.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from backtest.portfolio import SimulatedPortfolio


@dataclass
class BacktestResult:
    portfolio: SimulatedPortfolio
    equity_curve: list[tuple[str, float]] = field(default_factory=list)
    starting_cash: float = 0.0


def run(
    trades: list[dict],
    prices,                # PriceFetcher-like (has get_close_on)
    strategy,              # Strategy-like (has on_pub_date, check_exits, set_following, starting_cash, notional_per_trade)
    start_date: str,
    end_date: str,
) -> BacktestResult:
    portfolio = SimulatedPortfolio(starting_cash=strategy.starting_cash)
    by_pub: dict[str, list[dict]] = {}
    tickers_in_universe: set[str] = set()
    for t in trades:
        by_pub.setdefault(t["pub_date"], []).append(t)
        tickers_in_universe.add(t["ticker"])

    result = BacktestResult(portfolio=portfolio, starting_cash=strategy.starting_cash)

    for date_iso in _business_days(start_date, end_date):
        # Closes for held + relevant tickers — only fetch what we need
        current_prices: dict[str, float] = {}
        for ticker in list(portfolio.positions.keys()):
            c = prices.get_close_on(ticker, date_iso)
            if c is not None:
                current_prices[ticker] = c

        # Strategy-driven exits
        for action in strategy.check_exits(date_iso, portfolio, current_prices):
            if action.kind == "sell" and action.ticker in portfolio.positions:
                fill = current_prices.get(action.ticker)
                if fill:
                    portfolio.sell_all(action.ticker, fill_price=fill, date_iso=date_iso)

        # Filings published today
        new_filings = by_pub.get(date_iso, [])
        if new_filings:
            for action in strategy.on_pub_date(date_iso, new_filings):
                fill = prices.get_close_on(action.ticker, date_iso)
                if fill is None or fill <= 0:
                    continue
                if action.kind == "buy":
                    portfolio.buy(action.ticker, action.notional, fill, date_iso)
                elif action.kind == "sell" and action.ticker in portfolio.positions:
                    portfolio.sell_all(action.ticker, fill, date_iso)

        # End-of-day equity using cached closes
        eq = portfolio.equity(current_prices)
        result.equity_curve.append((date_iso, eq))

    return result


def _business_days(start_iso: str, end_iso: str):
    cur = datetime.strptime(start_iso, "%Y-%m-%d")
    end = datetime.strptime(end_iso, "%Y-%m-%d")
    while cur <= end:
        if cur.weekday() < 5:
            yield cur.strftime("%Y-%m-%d")
        cur += timedelta(days=1)
