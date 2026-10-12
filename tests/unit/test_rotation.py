"""ETF momentum rotation — pure signal + order-planning logic.

Backtest gate (CLAUDE.md §1): backtest/rotation_backtest.py drives the SAME
`rotation.signals.target_weights` used live. Report:
docs/2026-10-12-rotation.md.
"""
import pytest

from rotation.config import RotationConfig
from rotation.rebalance import plan_orders, rotation_budget
from rotation.signals import momentum_score, target_weights


CFG = RotationConfig(universe=("AAA", "BBB", "CCC", "DDD"), top_n=2, cash_symbol="CASHX",
                     lookbacks=(21, 63, 126, 252), sma_period=200)


def _series(n=300, start=100.0, step=0.0):
    return [start + step * i for i in range(n)]


# ── momentum ────────────────────────────────────────────────────────────────

def test_momentum_is_mean_of_lookback_returns():
    closes = _series(300, 100.0, 1.0)
    last = closes[-1]
    expected = sum(last / closes[-1 - k] - 1 for k in (21, 63, 126, 252)) / 4
    assert momentum_score(closes, CFG.lookbacks) == pytest.approx(expected)


def test_momentum_none_without_enough_history():
    assert momentum_score(_series(200), CFG.lookbacks) is None


# ── target weights ──────────────────────────────────────────────────────────

def test_picks_top_n_by_momentum_equal_weight():
    closes = {"AAA": _series(300, 100, 0.5), "BBB": _series(300, 100, 0.2),
              "CCC": _series(300, 100, 0.1), "DDD": _series(300, 100, -0.1)}
    w = target_weights(closes, CFG)
    assert w == pytest.approx({"AAA": 0.5, "BBB": 0.5})


def test_slot_below_sma_goes_to_cash():
    # BBB has the 2nd best 12m momentum but crashed below its SMA200 recently.
    bbb = _series(280, 100, 0.5) + [60.0] * 20
    closes = {"AAA": _series(300, 100, 0.5), "BBB": bbb,
              "CCC": _series(300, 100, -0.05), "DDD": _series(300, 100, -0.1)}
    w = target_weights(closes, CFG)
    assert "AAA" in w
    assert w.get("CASHX", 0) == pytest.approx(0.5)


def test_all_cash_when_nothing_has_history():
    w = target_weights({"AAA": _series(50)}, CFG)
    assert w == {"CASHX": 1.0}


def test_symbols_missing_data_are_skipped_not_fatal():
    closes = {"AAA": _series(300, 100, 0.5), "BBB": _series(300, 100, 0.2), "CCC": []}
    w = target_weights(closes, CFG)
    assert set(w) == {"AAA", "BBB"}


def test_excluded_symbols_are_never_selected():
    closes = {"AAA": _series(300, 100, 0.5), "BBB": _series(300, 100, 0.2),
              "CCC": _series(300, 100, 0.1)}
    w = target_weights(closes, CFG, exclude={"AAA"})
    assert "AAA" not in w and set(w) == {"BBB", "CCC"}


# ── budget ──────────────────────────────────────────────────────────────────

def test_budget_is_allocation_of_equity_when_cash_allows():
    assert rotation_budget(equity=1000, cash=900, current_value=0, alloc_pct=0.5, reserve_pct=0.3) == 500


def test_budget_keeps_cash_reserve_for_other_strategies():
    # 1000 equity, only 400 cash: may spend 400 − 300 reserve = 100 on top of what it holds.
    assert rotation_budget(equity=1000, cash=400, current_value=50, alloc_pct=0.5, reserve_pct=0.3) == 150


def test_budget_never_negative():
    assert rotation_budget(equity=1000, cash=100, current_value=0, alloc_pct=0.5, reserve_pct=0.3) == 0


# ── order plan ──────────────────────────────────────────────────────────────

def test_plan_sells_dropped_names_fully_and_buys_new_ones():
    orders = plan_orders(current={"AAA": 250.0, "OLD": 250.0}, held_qty={"AAA": 2.0, "OLD": 3.5},
                         weights={"AAA": 0.5, "BBB": 0.5}, budget=500.0, min_trade=5.0, drift_tol=0.1)
    assert orders[0] == ("SELL", "OLD", {"qty": 3.5})          # sells first, whole position
    assert ("BUY", "BBB", {"notional": 250.0}) in orders
    assert not any(o[1] == "AAA" for o in orders)                # on target → untouched


def test_plan_ignores_small_drift():
    orders = plan_orders(current={"AAA": 240.0}, held_qty={"AAA": 2.0},
                         weights={"AAA": 1.0}, budget=250.0, min_trade=5.0, drift_tol=0.1)
    assert orders == []


def test_plan_trims_large_overweight_by_notional():
    orders = plan_orders(current={"AAA": 400.0}, held_qty={"AAA": 4.0},
                         weights={"AAA": 0.5, "BBB": 0.5}, budget=500.0, min_trade=5.0, drift_tol=0.1)
    assert orders[0] == ("SELL", "AAA", {"notional": 150.0})
    assert ("BUY", "BBB", {"notional": 250.0}) in orders


def test_plan_skips_orders_below_min_trade():
    orders = plan_orders(current={}, held_qty={}, weights={"AAA": 1.0}, budget=3.0, min_trade=5.0, drift_tol=0.1)
    assert orders == []


def test_plan_buys_capped_by_budget_left_after_holdings():
    # Holding 300 of AAA (target 250, within tolerance? no: 20% over) → trim 50, buy BBB 250.
    orders = plan_orders(current={"AAA": 300.0}, held_qty={"AAA": 3.0},
                         weights={"AAA": 0.5, "BBB": 0.5}, budget=500.0, min_trade=5.0, drift_tol=0.1)
    buys = sum(o[2]["notional"] for o in orders if o[0] == "BUY")
    sells = sum(o[2].get("notional", 0) for o in orders if o[0] == "SELL")
    assert buys - sells <= 500.0 - 300.0 + 1e-9
