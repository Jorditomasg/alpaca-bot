"""Unit tests for wheel/summary.py — spread block, CSP block."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock


def _spread_state_open() -> dict:
    return {
        "strategy_type": "bull_put_spread",
        "stage": "SPREAD_OPEN",
        "symbol": "SOFI",
        "cycles": 2,
        "total_premium": 100.0,
        "premium_received": 50.0,
        "short_symbol": "SOFI260529P00009000",
        "short_strike": 9.0,
        "long_symbol": "SOFI260529P00007000",
        "long_strike": 7.0,
        "net_credit": 50.0,
        "max_loss": 150.0,
        "spread_width": 2.0,
        "contract_expiry": "2026-05-29",
        "contract_symbol": None,
        "contract_strike": None,
        "shares_owned": 0,
        "last_logged_insufficient_at": None,
    }


def _csp_state() -> dict:
    return {
        "strategy_type": "csp",
        "stage": "PUT_OPEN",
        "symbol": "SOFI",
        "cycles": 1,
        "total_premium": 120.0,
        "premium_received": 60.0,
        "contract_symbol": "SOFI260529P00009000",
        "contract_strike": 9.0,
        "contract_expiry": "2026-05-29",
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


# ── spread summary output ─────────────────────────────────────────────────────

def test_spread_summary_contains_required_fields(mocker, capsys):
    """Spread summary must include net credit, max loss, and both leg symbols."""
    import wheel.summary as summ

    mocker.patch("shared.alpaca_client.option_data", return_value=MagicMock(
        get_option_latest_quote=MagicMock(side_effect=Exception("no quote"))
    ))

    state = _spread_state_open()
    summ.print_summary(state)

    out = capsys.readouterr().out
    assert "SPREAD" in out.upper()
    assert "50.00" in out      # net credit
    assert "150.00" in out     # max loss
    assert "SOFI260529P00009000" in out   # short leg
    assert "SOFI260529P00007000" in out   # long leg


def test_spread_summary_shows_stage(mocker, capsys):
    import wheel.summary as summ

    mocker.patch("shared.alpaca_client.option_data", return_value=MagicMock(
        get_option_latest_quote=MagicMock(side_effect=Exception("no quote"))
    ))

    state = _spread_state_open()
    summ.print_summary(state)

    out = capsys.readouterr().out
    assert "SPREAD_OPEN" in out


def test_spread_summary_includes_cycles_and_total_premium(mocker, capsys):
    import wheel.summary as summ

    mocker.patch("shared.alpaca_client.option_data", return_value=MagicMock(
        get_option_latest_quote=MagicMock(side_effect=Exception("no quote"))
    ))

    state = _spread_state_open()
    summ.print_summary(state)

    out = capsys.readouterr().out
    assert "2" in out          # cycles
    assert "100.00" in out     # total premium


def test_spread_summary_with_live_mid(mocker, capsys):
    """If option quotes are available, spread mid-price and unrealised P&L appear."""
    import wheel.summary as summ

    mock_opt = MagicMock()
    short_q = MagicMock(bid_price=0.15, ask_price=0.18)
    long_q  = MagicMock(bid_price=0.04, ask_price=0.05)

    def _get_latest_quote(req):
        sym = req.symbol_or_symbols
        if sym == "SOFI260529P00009000":
            return {sym: short_q}
        return {sym: long_q}

    mock_opt.get_option_latest_quote.side_effect = _get_latest_quote
    mocker.patch("shared.alpaca_client.option_data", return_value=mock_opt)

    state = _spread_state_open()
    summ.print_summary(state)

    out = capsys.readouterr().out
    # spread_mid = short_bid - long_ask = 0.15 - 0.05 = 0.10
    # unrealised = (net_credit_per_share - current_mid) * 100 = (0.50 - 0.10)*100 = 40.0
    assert "0.1000" in out or "0.10" in out   # current mid
    assert "40.00" in out                      # unrealised P&L


# ── CSP backward-compatibility ────────────────────────────────────────────────

def test_csp_summary_still_works(mocker, capsys):
    """CSP strategy_type must still produce the original summary format."""
    import wheel.summary as summ

    mock_stock = MagicMock()
    trade = MagicMock(price=10.0)
    mock_stock.get_stock_latest_trade.return_value = {"SOFI": trade}
    mocker.patch("shared.alpaca_client.stock_data", return_value=mock_stock)

    state = _csp_state()
    summ.print_summary(state)

    out = capsys.readouterr().out
    assert "WHEEL STRATEGY" in out
    assert "PUT_OPEN" in out
    assert "120.00" in out     # total premium
    assert "SOFI260529P00009000" in out  # open contract
