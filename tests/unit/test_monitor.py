"""Unit tests for wheel/monitor.py — spread mode is engine-owned; CSP backward-compat."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock


def _spread_state_open(net_credit: float = 50.0) -> dict:
    return {
        "strategy_type": "bull_put_spread",
        "stage": "SPREAD_OPEN",
        "symbol": "SOFI",
        "cycles": 0,
        "total_premium": net_credit,
        "premium_received": net_credit,
        "short_symbol": "SOFI260529P00009000",
        "short_strike": 9.0,
        "long_symbol": "SOFI260529P00007000",
        "long_strike": 7.0,
        "net_credit": net_credit,
        "max_loss": 150.0,
        "spread_width": 2.0,
        "contract_expiry": "2026-05-29",
        "contract_symbol": None,
        "contract_strike": None,
        "last_logged_insufficient_at": None,
    }


# ── Spread mode: monitor must NOT submit orders (engine owns the close) ───────

def test_spread_mode_monitor_never_submits(mocker):
    """The engine's SPREAD_OPEN → SPREAD_CLOSING machine owns the profit-take.
    If the monitor also submitted a close, the same spread would be closed
    twice (the second untracked order re-opens the opposite position or gets
    rejected). Monitor must be a pure pass-through for spreads."""
    import wheel.monitor as mon

    mock_opt = MagicMock()
    mock_trading = MagicMock()
    mocker.patch("shared.alpaca_client.option_data", return_value=mock_opt)
    mocker.patch("shared.alpaca_client.trading", return_value=mock_trading)

    state = _spread_state_open(net_credit=50.0)
    result = mon.check_early_close(state)

    mock_trading.submit_order.assert_not_called()
    mock_opt.get_option_latest_quote.assert_not_called()
    assert result["stage"] == "SPREAD_OPEN"


def test_spread_mode_state_untouched(mocker):
    """check_early_close returns spread state unmodified."""
    import wheel.monitor as mon

    mocker.patch("shared.alpaca_client.trading", return_value=MagicMock())

    state = _spread_state_open(net_credit=50.0)
    before = dict(state)
    mon.check_early_close(state)

    assert state == before


# ── CSP backward-compatibility ────────────────────────────────────────────────

def test_csp_early_close_still_works(mocker):
    """check_early_close preserves legacy CSP behavior for strategy_type='csp'."""
    import wheel.monitor as mon

    mock_client = MagicMock()
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)
    mocker.patch("wheel.options.get_quote", return_value=0.10)  # 0.10 < 50% of 0.80 → close

    state = {
        "strategy_type": "csp",
        "stage": "PUT_OPEN",
        "contract_symbol": "SOFI260529P00009000",
        "premium_received": 80.0,  # 0.80/share; 50% = 0.40; current 0.10 < 0.40 → close
        "cycles": 0,
    }
    mon.check_early_close(state)

    # buy-to-close market order should be submitted
    mock_client.submit_order.assert_called_once()
    order = mock_client.submit_order.call_args[0][0]
    assert order.symbol == "SOFI260529P00009000"


def test_csp_no_close_above_target(mocker):
    """CSP: no buy-to-close while the option is still worth > 50% of premium."""
    import wheel.monitor as mon

    mock_client = MagicMock()
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)
    mocker.patch("wheel.options.get_quote", return_value=0.60)  # 0.60 > 0.40 → hold

    state = {
        "strategy_type": "csp",
        "stage": "PUT_OPEN",
        "contract_symbol": "SOFI260529P00009000",
        "premium_received": 80.0,
        "cycles": 0,
    }
    mon.check_early_close(state)

    mock_client.submit_order.assert_not_called()
