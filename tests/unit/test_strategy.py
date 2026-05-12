"""Unit tests for trailing/strategy.py — floor behavior + ATR-aware stops."""
from __future__ import annotations

import pytest
from trailing.strategy import evaluate, _compute_floor, DEFAULT_TRAIL_PCT


def _state(
    entry: float = 400.0,
    floor: float | None = None,
    atr: float | None = None,
    atr_multiplier: float = 2.5,
) -> dict:
    return {
        "entry_price": entry,
        "high_watermark": entry,
        "floor": floor if floor is not None else entry * 0.95,
        "trailing_active": False,
        "position_qty": 1.0,
        "ladder_15_done": False,
        "ladder_22_done": False,
        "ladder_30_done": False,
        "ladder_40_done": False,
        "atr": atr,
        "atr_multiplier": atr_multiplier,
    }


# ── Trigger activation precision ────────────────────────────────────────────


def test_trailing_activates_at_exactly_plus_10pct():
    """400 * 1.10 == 440.00000000000006 in FP — integer-cent compare must
    still let trailing activate at exactly +10%."""
    state = _state(entry=400.0)
    evaluate(440.00, state)
    assert state["trailing_active"] is True


def test_trailing_inactive_below_threshold():
    """Trailing must NOT activate at +9.99%."""
    state = _state(entry=400.0)
    evaluate(439.95, state)
    assert state["trailing_active"] is False


# ── Floor math (tight on every tick) ────────────────────────────────────────


def test_floor_moves_every_tick_tight_sl():
    """Floor must update on every tick that pushes the high watermark up —
    keeps the SL tight even when logs are throttled."""
    state = _state(entry=400.0)
    evaluate(441.00, state)
    first_floor = state["floor"]

    # Small upward tick: floor MUST still inch up (tight SL)
    evaluate(442.00, state)
    assert state["floor"] > first_floor, (
        "Floor must track the high watermark — tight SL is non-negotiable"
    )


def test_floor_monotonic_no_drop_on_dip():
    """Floor is monotonically increasing — dips do not lower it."""
    state = _state(entry=400.0)
    evaluate(441.00, state)
    evaluate(463.00, state)
    raised = state["floor"]

    evaluate(450.00, state)
    evaluate(455.00, state)
    assert state["floor"] == raised


# ── Log throttling (decoupled from floor math) ──────────────────────────────


def test_floor_log_not_emitted_on_tiny_tick(capsys):
    """Log line must NOT print on a few-cent upward move."""
    state = _state(entry=400.0)
    evaluate(441.00, state)
    capsys.readouterr()  # clear activation log

    evaluate(441.03, state)
    out = capsys.readouterr().out
    assert "Floor raised" not in out


def test_floor_log_emitted_on_meaningful_move(capsys):
    """Log must print when delta crosses the 1% threshold."""
    state = _state(entry=400.0)
    evaluate(441.00, state)
    capsys.readouterr()

    evaluate(463.00, state)  # +5% — well above threshold
    out = capsys.readouterr().out
    assert "Floor raised" in out


def test_log_count_under_steady_climb(capsys):
    """500 one-cent ticks must produce at most ~5 log lines, not 475."""
    state = _state(entry=400.0)
    evaluate(441.00, state)
    capsys.readouterr()

    price = 441.00
    for _ in range(500):
        price += 0.01
        evaluate(round(price, 2), state)

    raise_lines = [
        l for l in capsys.readouterr().out.splitlines() if "Floor raised" in l
    ]
    assert len(raise_lines) <= 5, (
        f"Floor raised {len(raise_lines)} times — log spam regression"
    )


def test_floor_tracks_tightly_under_steady_climb():
    """Floor must end ~5% below the final high watermark after a steady climb
    — proves the SL is NOT lagging behind."""
    state = _state(entry=400.0)
    evaluate(441.00, state)

    price = 441.00
    for _ in range(500):
        price += 0.01
        evaluate(round(price, 2), state)

    final_hwm = state["high_watermark"]
    expected_floor = round(final_hwm * (1 - DEFAULT_TRAIL_PCT), 2)
    # Floor must equal the formula — no lag from log throttling.
    assert state["floor"] == expected_floor, (
        f"Floor {state['floor']} != expected {expected_floor} "
        f"(hwm={final_hwm}) — SL is lagging"
    )


# ── ATR-based stop ──────────────────────────────────────────────────────────


def test_atr_overrides_default_pct_when_present():
    """When state has a positive atr, floor uses high_watermark - k*atr."""
    state = _state(entry=400.0, atr=8.0, atr_multiplier=2.0)
    state["high_watermark"] = 441.00
    # Expected: 441 - 2.0 * 8.0 = 425.00 (NOT 441 * 0.95 = 418.95)
    floor = _compute_floor(state)
    assert floor == 425.00


def test_atr_falls_back_when_zero_or_missing():
    """ATR=0 or missing → fixed-percentage fallback (high_watermark * 0.95)."""
    state = _state(entry=400.0, atr=0.0)
    state["high_watermark"] = 441.00
    assert _compute_floor(state) == round(441.00 * (1 - DEFAULT_TRAIL_PCT), 2)

    state2 = _state(entry=400.0)
    state2["atr"] = None
    state2["high_watermark"] = 441.00
    assert _compute_floor(state2) == round(441.00 * (1 - DEFAULT_TRAIL_PCT), 2)


def test_atr_floor_in_evaluate_tightens_stop():
    """Through evaluate(), ATR-based floor must replace the default 5% floor."""
    state = _state(entry=400.0, atr=4.0, atr_multiplier=2.5)
    evaluate(441.00, state)
    # Expected: 441 - 2.5 * 4.0 = 431.00
    assert state["floor"] == 431.00
