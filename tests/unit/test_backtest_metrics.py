"""Tests for backtest/metrics.py — return, sharpe, drawdown, etc."""
import math
import pytest
from backtest import metrics as bt_metrics


def test_total_return_pct_from_equity_curve():
    curve = [("2020-01-01", 10000.0), ("2020-12-31", 12000.0)]
    assert bt_metrics.total_return_pct(curve) == pytest.approx(20.0)


def test_total_return_pct_handles_loss():
    curve = [("2020-01-01", 10000.0), ("2020-12-31", 9000.0)]
    assert bt_metrics.total_return_pct(curve) == pytest.approx(-10.0)


def test_max_drawdown_pct_finds_worst_peak_to_trough():
    curve = [
        ("2020-01-01", 10000.0),
        ("2020-02-01", 12000.0),  # peak
        ("2020-03-01",  9000.0),  # trough → -25% from peak
        ("2020-04-01", 11000.0),  # recovery
    ]
    assert bt_metrics.max_drawdown_pct(curve) == pytest.approx(-25.0)


def test_max_drawdown_pct_zero_for_monotonic_increase():
    curve = [
        ("2020-01-01", 10000.0),
        ("2020-02-01", 11000.0),
        ("2020-03-01", 12000.0),
    ]
    assert bt_metrics.max_drawdown_pct(curve) == pytest.approx(0.0)


def test_cagr_handles_partial_year():
    # 10% gain over half a year → ~21% CAGR
    curve = [("2020-01-01", 10000.0), ("2020-07-02", 11000.0)]  # ~182 days
    cagr = bt_metrics.cagr_pct(curve)
    assert 19.0 < cagr < 24.0


def test_sharpe_ratio_positive_when_returns_outperform_rf():
    """Steady positive daily returns give high Sharpe; we just need it positive
    and finite (the exact value depends on noise we add to avoid zero stdev)."""
    import random
    random.seed(42)
    curve = [("2020-01-01", 10000.0)]
    eq = 10000.0
    for i in range(1, 252):
        # Positive mean (~0.1%/day) with small daily noise so stdev is nonzero
        eq *= 1.0 + 0.001 + random.uniform(-0.005, 0.005)
        curve.append((f"2020-day-{i}", eq))
    s = bt_metrics.sharpe_ratio(curve, risk_free_rate_annual=0.0)
    assert s > 1.0
    assert math.isfinite(s)


def test_win_rate_from_closed_trades():
    closed = [
        {"realized_pnl":  100.0},
        {"realized_pnl":  200.0},
        {"realized_pnl": -50.0},
        {"realized_pnl":  0.0},   # break-even — not a win
    ]
    assert bt_metrics.win_rate(closed) == pytest.approx(0.5)


def test_avg_holding_days_from_closed_trades():
    closed = [
        {"holding_days": 10},
        {"holding_days": 30},
        {"holding_days": 50},
    ]
    assert bt_metrics.avg_holding_days(closed) == pytest.approx(30.0)
