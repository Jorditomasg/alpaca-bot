"""Unit tests for wheel/engine.py — dispatch, capital guard, spread state machine, CSP smoke."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from datetime import date, timedelta


# ── helpers ───────────────────────────────────────────────────────────────────

_EXPIRY_FUTURE = str(date.today() + timedelta(days=60))  # well past expiry
_EXPIRY_PAST   = str(date.today() - timedelta(days=1))   # expired yesterday
_EXPIRY_TODAY  = str(date.today())                        # expires today → triggers expiry path


def _spread_state(stage: str = "IDLE", net_credit: float = 50.0, **kwargs) -> dict:
    """Build a minimal bull-put-spread state dict."""
    base = {
        "strategy_type": "bull_put_spread",
        "stage": stage,
        "symbol": "SOFI",
        "cycles": 0,
        "total_premium": 0.0,
        "premium_received": 0.0,
        "contract_symbol": None,
        "contract_strike": None,
        "contract_expiry": None,
        "cost_basis": None,
        "shares_owned": 0,
        "short_symbol": "SOFI260117P00009000",
        "short_strike": 9.0,
        "long_symbol": "SOFI260117P00007000",
        "long_strike": 7.0,
        "net_credit": net_credit,
        "max_loss": 150.0,
        "spread_width": 2.0,
        "last_logged_insufficient_at": None,
    }
    if stage == "SPREAD_OPEN":
        base["contract_expiry"] = _EXPIRY_FUTURE
    base.update(kwargs)
    return base


def _csp_state(stage: str = "IDLE") -> dict:
    return {
        "strategy_type": "csp",
        "stage": stage,
        "symbol": "SOFI",
        "cycles": 0,
        "total_premium": 120.0,
        "premium_received": 60.0,
        "contract_symbol": "SOFI260117P00009000",
        "contract_strike": 9.0,
        "contract_expiry": _EXPIRY_FUTURE,
        "cost_basis": None,
        "shares_owned": 0,
        "short_symbol": None,
        "short_strike": None,
        "long_symbol": None,
        "long_strike": None,
        "net_credit": 0.0,
        "max_loss": 0.0,
        "spread_width": 2.0,
        "last_logged_insufficient_at": None,
    }


# ── dispatcher ────────────────────────────────────────────────────────────────

def test_dispatch_calls_spread_cycle(mocker):
    """run_cycle dispatches to _run_spread_cycle when strategy_type='bull_put_spread'."""
    import wheel.engine as eng
    mock_spread = mocker.patch.object(eng, "_run_spread_cycle", return_value={"stage": "IDLE"})
    mocker.patch.object(eng, "_run_csp_cycle", return_value={"stage": "IDLE"})

    state = _spread_state()
    eng.run_cycle(state)

    mock_spread.assert_called_once()
    eng._run_csp_cycle.assert_not_called()


def test_dispatch_calls_csp_cycle(mocker):
    """run_cycle dispatches to _run_csp_cycle when strategy_type='csp'."""
    import wheel.engine as eng
    mocker.patch.object(eng, "_run_spread_cycle", return_value={"stage": "IDLE"})
    mock_csp = mocker.patch.object(eng, "_run_csp_cycle", return_value={"stage": "IDLE"})

    state = _csp_state()
    eng.run_cycle(state)

    mock_csp.assert_called_once()
    eng._run_spread_cycle.assert_not_called()


# ── capital guard ─────────────────────────────────────────────────────────────

def test_capital_guard_logs_on_first_insufficient(mocker, capsys, monkeypatch):
    """Capital guard logs exactly once when buying power first drops below threshold."""
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    mock_client.get_account.return_value = MagicMock(buying_power="300")
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)

    state = _spread_state()
    eng.run_cycle(state)

    out = capsys.readouterr().out
    assert "Insufficient buying power" in out
    assert state["stage"] == "IDLE"  # no state change when capital guard fires


def test_capital_guard_silent_on_second_cycle_same_bp(mocker, capsys, monkeypatch):
    """Capital guard does NOT log again when buying power stays at the same level."""
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    mock_client.get_account.return_value = MagicMock(buying_power="300")
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)

    state = _spread_state()
    # First cycle — should log
    eng.run_cycle(state)
    out1 = capsys.readouterr().out
    assert "Insufficient buying power" in out1

    # Second cycle — same BP → same bucket → SILENT
    eng.run_cycle(state)
    out2 = capsys.readouterr().out
    assert "Insufficient buying power" not in out2


def test_capital_guard_relogs_when_bp_changes(mocker, capsys, monkeypatch):
    """Capital guard re-logs when buying power changes (new bucket)."""
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)

    state = _spread_state()

    # First cycle at $300
    mock_client.get_account.return_value = MagicMock(buying_power="300")
    eng.run_cycle(state)
    capsys.readouterr()  # clear

    # Second cycle at $250 (different bucket) → should re-log
    mock_client.get_account.return_value = MagicMock(buying_power="250")
    eng.run_cycle(state)
    out = capsys.readouterr().out
    assert "Insufficient buying power" in out


def test_capital_guard_clears_on_recovery(mocker, capsys, monkeypatch):
    """Capital guard latch clears when buying power recovers above threshold."""
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)
    mocker.patch.object(eng, "_open_spread", return_value=_spread_state())

    state = _spread_state()

    # First insufficient cycle
    mock_client.get_account.return_value = MagicMock(buying_power="300")
    eng.run_cycle(state)
    capsys.readouterr()

    # Recovery cycle — latch should be cleared
    mock_client.get_account.return_value = MagicMock(buying_power="500")
    eng.run_cycle(state)
    assert state["last_logged_insufficient_at"] is None


# ── IDLE → SPREAD_OPEN ────────────────────────────────────────────────────────

def test_idle_to_spread_open_happy_path(mocker, monkeypatch):
    """IDLE → SPREAD_OPEN when capital is sufficient and a qualifying spread is found."""
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    mock_client.get_account.return_value = MagicMock(buying_power="1000")
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)
    mocker.patch.object(eng, "_get_stock_price", return_value=10.0)
    mocker.patch.object(eng, "_fetch_option_chain", return_value={
        "spot_price": 10.0,
        "contracts": [],  # empty; we mock best_bull_put_spread directly
    })
    mocker.patch("wheel.spreads.best_bull_put_spread", return_value={
        "short_symbol": "SOFI260117P00009000",
        "short_strike": 9.0,
        "long_symbol": "SOFI260117P00007000",
        "long_strike": 7.0,
        "expiry": _EXPIRY_FUTURE,
        "net_credit": 50.0,
        "max_loss": 150.0,
        "width": 2.0,
        "score": 0.33,
    })

    state = _spread_state(stage="IDLE")
    result = eng.run_cycle(state)

    assert result["stage"] == "SPREAD_OPEN"
    assert result["short_symbol"] == "SOFI260117P00009000"
    assert result["net_credit"] == 50.0
    mock_client.submit_order.assert_called_once()


def test_idle_stays_when_no_spread_found(mocker, monkeypatch):
    """IDLE stays IDLE when best_bull_put_spread returns None."""
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    mock_client.get_account.return_value = MagicMock(buying_power="1000")
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)
    mocker.patch.object(eng, "_get_stock_price", return_value=10.0)
    mocker.patch.object(eng, "_fetch_option_chain", return_value={"spot_price": 10.0, "contracts": []})
    mocker.patch("wheel.spreads.best_bull_put_spread", return_value=None)

    state = _spread_state(stage="IDLE")
    result = eng.run_cycle(state)

    assert result["stage"] == "IDLE"
    mock_client.submit_order.assert_not_called()


# ── SPREAD_OPEN → IDLE (profit-take) ─────────────────────────────────────────

def test_spread_open_to_idle_profit_take(mocker, monkeypatch):
    """SPREAD_OPEN → IDLE when current spread cost ≤ 50% of net credit."""
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    mock_client.get_account.return_value = MagicMock(buying_power="1000")
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)

    # net_credit = 50.0 → per-share credit = 0.50
    # profit target at 50%: cost ≤ 0.50 * (1 - 0.50) = 0.25
    # We'll say short_bid=0.15, long_ask=0.05 → spread_mid=0.10 ≤ 0.25 → trigger
    mocker.patch.object(eng, "_get_option_quote", side_effect=[
        {"bid": 0.15, "ask": 0.18},   # short quote
        {"bid": 0.04, "ask": 0.05},   # long quote
    ])

    state = _spread_state(stage="SPREAD_OPEN", net_credit=50.0)
    state["contract_expiry"] = _EXPIRY_FUTURE
    result = eng.run_cycle(state)

    assert result["stage"] == "IDLE"
    assert result["cycles"] == 1
    assert result["short_symbol"] is None
    mock_client.submit_order.assert_called_once()


def test_spread_open_stays_when_mid_above_target(mocker, monkeypatch):
    """SPREAD_OPEN stays when current spread cost > profit target."""
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    mock_client.get_account.return_value = MagicMock(buying_power="1000")
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)

    # net_credit=50.0 → target = 0.25/share; mid = 0.40 → no close
    mocker.patch.object(eng, "_get_option_quote", side_effect=[
        {"bid": 0.45, "ask": 0.50},   # short (expensive to close)
        {"bid": 0.04, "ask": 0.05},   # long
    ])

    state = _spread_state(stage="SPREAD_OPEN", net_credit=50.0)
    state["contract_expiry"] = _EXPIRY_FUTURE
    result = eng.run_cycle(state)

    assert result["stage"] == "SPREAD_OPEN"
    mock_client.submit_order.assert_not_called()


# ── SPREAD_OPEN → IDLE (expiry worthless) ────────────────────────────────────

def test_spread_expires_worthless(mocker, monkeypatch):
    """SPREAD_OPEN → IDLE when spread expires and underlying > long_strike."""
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    mock_client.get_account.return_value = MagicMock(buying_power="1000")
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)
    # underlying = 9.5 (above long_strike=7.0) → worthless expiry
    mocker.patch.object(eng, "_get_stock_price", return_value=9.5)

    state = _spread_state(stage="SPREAD_OPEN", net_credit=50.0)
    state["contract_expiry"] = _EXPIRY_PAST  # expired yesterday

    result = eng.run_cycle(state)

    assert result["stage"] == "IDLE"
    assert result["cycles"] == 1
    # Full credit was already in total_premium; no deduction for worthless expiry
    assert result["short_symbol"] is None


# ── SPREAD_OPEN → IDLE (max-loss) ────────────────────────────────────────────

def test_spread_max_loss_at_expiry(mocker, monkeypatch):
    """SPREAD_OPEN → IDLE when underlying closes below long_strike at expiry."""
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    mock_client.get_account.return_value = MagicMock(buying_power="1000")
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)
    # underlying = 6.0 (below long_strike=7.0) → max loss
    mocker.patch.object(eng, "_get_stock_price", return_value=6.0)

    state = _spread_state(stage="SPREAD_OPEN", net_credit=50.0)
    state["contract_expiry"] = _EXPIRY_PAST
    state["total_premium"] = 50.0  # started with the credit

    result = eng.run_cycle(state)

    assert result["stage"] == "IDLE"
    assert result["cycles"] == 1
    # total_premium should have been reduced by max_loss (150.0)
    assert result["total_premium"] == pytest.approx(50.0 - 150.0, abs=0.01)


# ── Expiry P&L three-region accounting (Fix #1) ──────────────────────────────

def test_expiry_above_short_strike_full_credit(mocker, monkeypatch):
    """Spot >= short_strike → both legs worthless, full credit kept.

    short=$9, long=$7, credit=$40 (net_credit=40.0), spot=$9.50
    realized = $40; total_premium unchanged (credit already booked at open).
    """
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    mock_client.get_account.return_value = MagicMock(buying_power="1000")
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)
    mocker.patch.object(eng, "_get_stock_price", return_value=9.5)

    state = _spread_state(stage="SPREAD_OPEN", net_credit=40.0)
    state["short_strike"] = 9.0
    state["long_strike"] = 7.0
    state["max_loss"] = 160.0  # (2*100) - 40
    state["contract_expiry"] = _EXPIRY_PAST
    state["total_premium"] = 40.0  # credit booked at open

    result = eng.run_cycle(state)

    assert result["stage"] == "IDLE"
    assert result["cycles"] == 1
    # total_premium unchanged — worthless expiry, credit already counted
    assert result["total_premium"] == pytest.approx(40.0, abs=0.01)
    # realized_pnl accumulates the net_credit
    assert result["realized_pnl"] == pytest.approx(40.0, abs=0.01)


def test_expiry_between_strikes_partial_loss(mocker, monkeypatch):
    """Spot between strikes → partial loss (short ITM, long OTM).

    short=$9, long=$7, credit=$40 (net_credit=40.0), spot=$8.50
    intrinsic = (9 - 8.50) * 100 = $50
    realized = max(-160, 40 - 50) = max(-160, -10) = -$10
    total_premium adjustment: reverse +40, apply -10 → net change = -50
    total_premium_before=40 → total_premium_after = 40 - 40 + (-10) = -10
    """
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    mock_client.get_account.return_value = MagicMock(buying_power="1000")
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)
    mocker.patch.object(eng, "_get_stock_price", return_value=8.50)

    state = _spread_state(stage="SPREAD_OPEN", net_credit=40.0)
    state["short_strike"] = 9.0
    state["long_strike"] = 7.0
    state["max_loss"] = 160.0  # (2*100) - 40
    state["contract_expiry"] = _EXPIRY_PAST
    state["total_premium"] = 40.0  # credit booked at open

    result = eng.run_cycle(state)

    assert result["stage"] == "IDLE"
    assert result["cycles"] == 1
    # Realized is partial loss: credit - intrinsic = 40 - 50 = -10
    assert result["realized_pnl"] == pytest.approx(-10.0, abs=0.01)
    # total_premium: 40 (initial) - 40 (reverse credit) + (-10) (realized) = -10
    assert result["total_premium"] == pytest.approx(-10.0, abs=0.01)
    # Critically: realized (-10) is NOT equal to full credit (40)
    # and NOT equal to -max_loss (-160) — it's in between
    assert result["realized_pnl"] != pytest.approx(40.0, abs=0.01)
    assert result["realized_pnl"] != pytest.approx(-160.0, abs=0.01)


def test_expiry_below_long_strike_full_max_loss(mocker, monkeypatch):
    """Spot < long_strike → full max loss.

    short=$9, long=$7, credit=$40 (net_credit=40.0), spot=$6.50
    realized = net_credit - max_loss = 40 - 160 = -$120
    total_premium: 40 - 40 + (-120) = -120
    """
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    mock_client.get_account.return_value = MagicMock(buying_power="1000")
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)
    mocker.patch.object(eng, "_get_stock_price", return_value=6.50)

    state = _spread_state(stage="SPREAD_OPEN", net_credit=40.0)
    state["short_strike"] = 9.0
    state["long_strike"] = 7.0
    state["max_loss"] = 160.0  # (2*100) - 40
    state["contract_expiry"] = _EXPIRY_PAST
    state["total_premium"] = 40.0  # credit booked at open

    result = eng.run_cycle(state)

    assert result["stage"] == "IDLE"
    assert result["cycles"] == 1
    # realized = 40 - 160 = -120
    assert result["realized_pnl"] == pytest.approx(-120.0, abs=0.01)
    # total_premium = 40 - 40 + (-120) = -120
    assert result["total_premium"] == pytest.approx(-120.0, abs=0.01)


def test_partial_loss_total_premium_not_full_credit(mocker, monkeypatch):
    """total_premium does NOT increment by full credit on a partial-loss close.

    This verifies the silent mis-accounting bug is fixed: previously a partial-loss
    scenario would leave total_premium at the full credit amount.
    """
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    mock_client.get_account.return_value = MagicMock(buying_power="1000")
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)
    # spot=8.50, short=9, long=7 → partial loss
    mocker.patch.object(eng, "_get_stock_price", return_value=8.50)

    state = _spread_state(stage="SPREAD_OPEN", net_credit=40.0)
    state["short_strike"] = 9.0
    state["long_strike"] = 7.0
    state["max_loss"] = 160.0
    state["contract_expiry"] = _EXPIRY_PAST
    state["total_premium"] = 40.0

    result = eng.run_cycle(state)

    # After partial loss, total_premium must NOT be 40 (full credit)
    assert result["total_premium"] != pytest.approx(40.0, abs=0.01)
    # And must NOT be 0 (as if no trade happened)
    assert result["total_premium"] != pytest.approx(0.0, abs=0.01)


# ── Capital guard scope (Fix #2) ─────────────────────────────────────────────

def test_capital_guard_does_not_block_spread_close(mocker, monkeypatch):
    """SPREAD_OPEN with BP < min must NOT be blocked by capital guard.

    State=SPREAD_OPEN, BP=$50 (below any reasonable threshold).
    A 50%-profit opportunity exists. Guard must not halt; close must fire.
    """
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    # BP well below threshold — if guard ran unconditionally this would halt
    mock_client.get_account.return_value = MagicMock(buying_power="50")
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)

    # net_credit=50 → per-share=0.50; target=0.25; mid=0.10 → triggers close
    mocker.patch.object(eng, "_get_option_quote", side_effect=[
        {"bid": 0.15, "ask": 0.18},  # short
        {"bid": 0.04, "ask": 0.05},  # long
    ])

    state = _spread_state(stage="SPREAD_OPEN", net_credit=50.0)
    state["contract_expiry"] = _EXPIRY_FUTURE

    result = eng.run_cycle(state)

    # Close must have executed despite low BP
    assert result["stage"] == "IDLE"
    assert result["cycles"] == 1
    mock_client.submit_order.assert_called_once()


def test_capital_guard_still_halts_idle(mocker, capsys, monkeypatch):
    """IDLE with BP < min must still be halted by capital guard (regression)."""
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    mock_client.get_account.return_value = MagicMock(buying_power="50")
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)

    state = _spread_state(stage="IDLE")
    result = eng.run_cycle(state)

    assert result["stage"] == "IDLE"
    mock_client.submit_order.assert_not_called()
    out = capsys.readouterr().out
    assert "Insufficient buying power" in out


# ── Order-before-state-mutation (Fix #9) ─────────────────────────────────────

def test_open_spread_submit_raises_state_stays_idle(mocker, monkeypatch):
    """If submit_order raises, state must remain IDLE with no spread fields mutated.

    The engine builds candidate state but MUST NOT commit it before order is accepted.
    """
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    mock_client.get_account.return_value = MagicMock(buying_power="1000")
    mock_client.submit_order.side_effect = RuntimeError("order rejected")
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)

    mocker.patch.object(eng, "_get_stock_price", return_value=10.0)
    mocker.patch.object(eng, "_fetch_option_chain", return_value={
        "spot_price": 10.0,
        "contracts": [],
    })
    mocker.patch("wheel.spreads.best_bull_put_spread", return_value={
        "short_symbol": "SOFI260117P00009000",
        "short_strike": 9.0,
        "long_symbol": "SOFI260117P00007000",
        "long_strike": 7.0,
        "expiry": _EXPIRY_FUTURE,
        "net_credit": 50.0,
        "max_loss": 150.0,
        "width": 2.0,
        "score": 0.33,
    })

    # Start from a clean IDLE state (no pre-populated spread symbols)
    state = {
        "strategy_type": "bull_put_spread",
        "stage": "IDLE",
        "symbol": "SOFI",
        "cycles": 0,
        "total_premium": 0.0,
        "premium_received": 0.0,
        "contract_symbol": None,
        "contract_strike": None,
        "contract_expiry": None,
        "cost_basis": None,
        "shares_owned": 0,
        "short_symbol": None,   # clean slate
        "short_strike": None,
        "long_symbol": None,
        "long_strike": None,
        "net_credit": 0.0,
        "max_loss": 0.0,
        "spread_width": 2.0,
        "last_logged_insufficient_at": None,
        "realized_pnl": 0.0,
    }
    result = eng.run_cycle(state)

    # State must remain IDLE — order failed, no mutation committed
    assert result["stage"] == "IDLE"
    assert result["short_symbol"] is None
    assert result["long_symbol"] is None
    assert result["net_credit"] == 0.0
    assert result["total_premium"] == 0.0


# ── Spread fields cleared on reset (Fix #7) ──────────────────────────────────

def test_contract_expiry_cleared_after_close(mocker, monkeypatch):
    """After a spread closes (profit-take), IDLE state must have no stale contract_expiry."""
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "400")
    import wheel.engine as eng

    mock_client = MagicMock()
    mock_client.get_account.return_value = MagicMock(buying_power="1000")
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)

    # Trigger profit-take: mid=0.10 <= target=0.25 (net_credit=50, 50% default)
    mocker.patch.object(eng, "_get_option_quote", side_effect=[
        {"bid": 0.15, "ask": 0.18},
        {"bid": 0.04, "ask": 0.05},
    ])

    state = _spread_state(stage="SPREAD_OPEN", net_credit=50.0)
    state["contract_expiry"] = _EXPIRY_FUTURE

    result = eng.run_cycle(state)

    assert result["stage"] == "IDLE"
    # contract_expiry must be cleared — no stale expiry leaks into IDLE
    assert result["contract_expiry"] is None


# ── CSP regression smoke ──────────────────────────────────────────────────────

def test_csp_idle_tries_to_open_put(mocker):
    """CSP IDLE stage calls _open_put (legacy behavior preserved)."""
    import wheel.engine as eng
    mock_open_put = mocker.patch.object(eng, "_open_put", return_value=_csp_state("PUT_OPEN"))

    state = _csp_state(stage="IDLE")
    result = eng.run_cycle(state)

    mock_open_put.assert_called_once_with(state, state["symbol"])


def test_csp_does_not_reach_spread_open(mocker):
    """CSP engine never transitions to SPREAD_OPEN."""
    import wheel.engine as eng
    mocker.patch.object(eng, "_open_put", return_value=_csp_state("PUT_OPEN"))

    state = _csp_state(stage="IDLE")
    result = eng.run_cycle(state)

    assert result["stage"] != "SPREAD_OPEN"
