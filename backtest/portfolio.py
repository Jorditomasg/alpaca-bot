"""Simulated portfolio for backtests.

No broker calls. Tracks cash, positions, fills. Mark-to-market via injected
prices. Designed to be deterministic — replay the same trades and you get the
same equity curve every time.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Position:
    ticker: str
    qty: float
    cost_basis: float       # weighted-avg entry price
    entry_date: str         # ISO date of first buy
    high_watermark: float = 0.0  # max close seen since entry (for trailing exits)


@dataclass
class SimulatedPortfolio:
    starting_cash: float
    cash: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    trades_log: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cash = self.starting_cash

    def buy(self, ticker: str, notional: float, fill_price: float, date_iso: str) -> bool:
        if notional > self.cash:
            return False
        if fill_price <= 0:
            return False

        qty = notional / fill_price
        self.cash -= notional

        if ticker in self.positions:
            existing = self.positions[ticker]
            total_qty = existing.qty + qty
            existing.cost_basis = (
                (existing.cost_basis * existing.qty + fill_price * qty) / total_qty
            )
            existing.qty = total_qty
        else:
            self.positions[ticker] = Position(
                ticker=ticker,
                qty=qty,
                cost_basis=fill_price,
                entry_date=date_iso,
                high_watermark=fill_price,
            )

        self.trades_log.append({
            "date": date_iso, "side": "buy", "ticker": ticker,
            "qty": qty, "price": fill_price, "notional": notional,
        })
        return True

    def sell_all(self, ticker: str, fill_price: float, date_iso: str) -> float:
        if ticker not in self.positions:
            return 0.0
        pos = self.positions.pop(ticker)
        proceeds = pos.qty * fill_price
        realized = proceeds - (pos.cost_basis * pos.qty)
        self.cash += proceeds
        self.trades_log.append({
            "date": date_iso, "side": "sell", "ticker": ticker,
            "qty": pos.qty, "price": fill_price, "notional": proceeds,
            "realized_pnl": realized,
            "holding_days": _days_between(pos.entry_date, date_iso),
            "return_pct": (fill_price / pos.cost_basis - 1.0) * 100.0,
        })
        return realized

    def equity(self, prices: dict[str, float]) -> float:
        total = self.cash
        for ticker, pos in self.positions.items():
            mark = prices.get(ticker)
            total += pos.qty * (mark if mark is not None else pos.cost_basis)
        return total


def _days_between(start_iso: str, end_iso: str) -> int:
    from datetime import datetime
    s = datetime.strptime(start_iso, "%Y-%m-%d")
    e = datetime.strptime(end_iso, "%Y-%m-%d")
    return (e - s).days
