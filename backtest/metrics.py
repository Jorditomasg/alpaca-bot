"""Performance metrics for backtest results.

All functions operate on the standard equity curve format:
    list[tuple[date_iso, equity_float]]

Closed-trade metrics expect the sell-side fills emitted by SimulatedPortfolio
(which include realized_pnl and holding_days).
"""
from __future__ import annotations
import math
import statistics
from datetime import datetime


def total_return_pct(curve: list[tuple[str, float]]) -> float:
    if len(curve) < 2:
        return 0.0
    start = curve[0][1]
    end = curve[-1][1]
    if start <= 0:
        return 0.0
    return (end / start - 1.0) * 100.0


def max_drawdown_pct(curve: list[tuple[str, float]]) -> float:
    if len(curve) < 2:
        return 0.0
    peak = curve[0][1]
    worst = 0.0
    for _, eq in curve:
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (eq / peak - 1.0) * 100.0
            if dd < worst:
                worst = dd
    return worst


def cagr_pct(curve: list[tuple[str, float]]) -> float:
    if len(curve) < 2:
        return 0.0
    start_date = datetime.strptime(curve[0][0], "%Y-%m-%d")
    end_date = datetime.strptime(curve[-1][0], "%Y-%m-%d")
    years = (end_date - start_date).days / 365.25
    if years <= 0:
        return 0.0
    start_eq = curve[0][1]
    end_eq = curve[-1][1]
    if start_eq <= 0:
        return 0.0
    return ((end_eq / start_eq) ** (1.0 / years) - 1.0) * 100.0


def sharpe_ratio(curve: list[tuple[str, float]], risk_free_rate_annual: float = 0.0) -> float:
    """Annualized Sharpe based on daily equity returns.

    risk_free_rate_annual is a decimal (0.04 = 4% annual).
    """
    if len(curve) < 3:
        return 0.0
    daily_returns: list[float] = []
    for i in range(1, len(curve)):
        prev = curve[i - 1][1]
        cur = curve[i][1]
        if prev > 0:
            daily_returns.append(cur / prev - 1.0)
    if len(daily_returns) < 2:
        return 0.0
    mean = statistics.mean(daily_returns)
    std = statistics.stdev(daily_returns)
    if std == 0:
        return 0.0
    rf_daily = risk_free_rate_annual / 252.0
    excess = mean - rf_daily
    return (excess / std) * math.sqrt(252.0)


def win_rate(closed_trades: list[dict]) -> float:
    if not closed_trades:
        return 0.0
    wins = sum(1 for t in closed_trades if t.get("realized_pnl", 0.0) > 0)
    return wins / len(closed_trades)


def avg_holding_days(closed_trades: list[dict]) -> float:
    days = [t.get("holding_days", 0) for t in closed_trades]
    if not days:
        return 0.0
    return statistics.mean(days)


def summarize(result, closed_trades: list[dict]) -> dict:
    """Bundle the standard metrics for a backtest run into one dict."""
    curve = result.equity_curve
    return {
        "starting_equity": curve[0][1] if curve else 0.0,
        "ending_equity": curve[-1][1] if curve else 0.0,
        "total_return_pct": total_return_pct(curve),
        "cagr_pct": cagr_pct(curve),
        "max_drawdown_pct": max_drawdown_pct(curve),
        "sharpe": sharpe_ratio(curve),
        "n_closed_trades": len(closed_trades),
        "win_rate": win_rate(closed_trades),
        "avg_holding_days": avg_holding_days(closed_trades),
    }
