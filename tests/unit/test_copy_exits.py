"""Tests for copy_trader/exits.py — per-position exit policy."""
import pytest
from copy_trader import exits as ex


def _pos(entry_date="2026-04-01", cost_basis=100.0, high_watermark=100.0):
    return {
        "entry_date": entry_date,
        "cost_basis": cost_basis,
        "high_watermark": high_watermark,
        "notional": 200.0,
    }


def test_no_exit_when_price_within_band():
    positions = {"AAPL": _pos(cost_basis=100.0)}
    prices = {"AAPL": 101.0}

    decisions = ex.evaluate(
        positions, prices, today="2026-04-15",
        stop_loss_pct=8.0, trail_arm_pct=8.0, trail_giveback_pct=5.0, max_holding_days=180,
    )

    assert decisions == []


def test_stop_loss_triggers_when_drawdown_exceeds_threshold():
    positions = {"AAPL": _pos(cost_basis=100.0)}
    prices = {"AAPL": 91.0}  # -9% from cost basis

    decisions = ex.evaluate(
        positions, prices, today="2026-04-15",
        stop_loss_pct=8.0, trail_arm_pct=8.0, trail_giveback_pct=5.0, max_holding_days=180,
    )

    assert len(decisions) == 1
    assert decisions[0].ticker == "AAPL"
    assert decisions[0].reason == "stop_loss"


def test_trailing_stop_triggers_after_arm_and_giveback():
    """HWM at 120 (20% gain — armed). Then price drops to 113 → below 120*0.95 = 114."""
    positions = {"AAPL": _pos(cost_basis=100.0, high_watermark=120.0)}
    prices = {"AAPL": 113.0}

    decisions = ex.evaluate(
        positions, prices, today="2026-04-15",
        stop_loss_pct=8.0, trail_arm_pct=8.0, trail_giveback_pct=5.0, max_holding_days=180,
    )

    assert len(decisions) == 1
    assert decisions[0].reason == "trailing_stop"


def test_trailing_not_armed_until_peak_gain_crosses_threshold():
    """HWM at 105 (5% — not yet armed at 8%). Drop to 95 → only stop_loss possible (not yet triggered at -5%)."""
    positions = {"AAPL": _pos(cost_basis=100.0, high_watermark=105.0)}
    prices = {"AAPL": 99.0}

    decisions = ex.evaluate(
        positions, prices, today="2026-04-15",
        stop_loss_pct=8.0, trail_arm_pct=8.0, trail_giveback_pct=5.0, max_holding_days=180,
    )

    assert decisions == []


def test_max_holding_signal_expired():
    positions = {"AAPL": _pos(entry_date="2026-01-01", cost_basis=100.0)}
    prices = {"AAPL": 101.0}

    decisions = ex.evaluate(
        positions, prices, today="2026-07-01",
        stop_loss_pct=8.0, trail_arm_pct=8.0, trail_giveback_pct=5.0, max_holding_days=180,
    )

    assert len(decisions) == 1
    assert decisions[0].reason == "signal_expired"


def test_high_watermark_advances_on_new_high():
    """The function should update HWM in-place so trailing logic tracks correctly."""
    positions = {"AAPL": _pos(cost_basis=100.0, high_watermark=100.0)}
    prices = {"AAPL": 115.0}

    ex.evaluate(
        positions, prices, today="2026-04-15",
        stop_loss_pct=8.0, trail_arm_pct=8.0, trail_giveback_pct=5.0, max_holding_days=180,
    )

    assert positions["AAPL"]["high_watermark"] == 115.0


def test_missing_price_no_exit():
    """No price → can't decide → skip (don't crash)."""
    positions = {"AAPL": _pos(cost_basis=100.0)}
    prices = {}

    decisions = ex.evaluate(
        positions, prices, today="2026-04-15",
        stop_loss_pct=8.0, trail_arm_pct=8.0, trail_giveback_pct=5.0, max_holding_days=180,
    )

    assert decisions == []


def test_missing_metadata_no_exit():
    """Legacy position without cost_basis/entry_date can't be evaluated — skip."""
    positions = {"AAPL": {"notional": 100.0}}
    prices = {"AAPL": 50.0}  # would normally be -50% but we have no cost_basis

    decisions = ex.evaluate(
        positions, prices, today="2026-04-15",
        stop_loss_pct=8.0, trail_arm_pct=8.0, trail_giveback_pct=5.0, max_holding_days=180,
    )

    assert decisions == []
