"""Unit tests for wheel/monitor.py — spread mid calculation and CSP backward-compat."""
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


def _make_quote_mock(bid: float, ask: float):
    """Return a MagicMock with bid_price and ask_price attributes."""
    q = MagicMock()
    q.bid_price = bid
    q.ask_price = ask
    return q


def _make_option_data_mock(quotes: dict[str, tuple[float, float]]) -> MagicMock:
    """Build an option_data client mock that returns correct quotes by symbol.

    quotes: {symbol: (bid, ask)}
    """
    client = MagicMock()

    def _get_latest_quote(req):
        sym = req.symbol_or_symbols
        bid, ask = quotes[sym]
        return {sym: _make_quote_mock(bid, ask)}

    client.get_option_latest_quote.side_effect = _get_latest_quote
    return client


# ── spread mid-price calculation ──────────────────────────────────────────────

def test_spread_mid_price_below_target_triggers_close(mocker):
    """When spread mid <= 50% of net credit, close order is submitted."""
    import wheel.monitor as mon

    # net_credit = 50.0 → per-share = 0.50; 50% target = 0.25
    # short_bid=0.15, long_ask=0.05 → spread_mid = 0.10 <= 0.25 → trigger
    mock_opt = _make_option_data_mock({
        "SOFI260529P00009000": (0.15, 0.18),
        "SOFI260529P00007000": (0.04, 0.05),
    })
    mock_trading = MagicMock()
    mocker.patch("shared.alpaca_client.option_data", return_value=mock_opt)
    mocker.patch("shared.alpaca_client.trading", return_value=mock_trading)

    state = _spread_state_open(net_credit=50.0)
    mon.check_early_close(state)

    mock_trading.submit_order.assert_called_once()


def test_spread_mid_price_above_target_no_close(mocker):
    """When spread mid > 50% of net credit, no close order is submitted."""
    import wheel.monitor as mon

    # net_credit = 50.0 → target = 0.25/share
    # short_bid=0.38, long_ask=0.05 → spread_mid = 0.33 > 0.25 → no close
    mock_opt = _make_option_data_mock({
        "SOFI260529P00009000": (0.38, 0.42),
        "SOFI260529P00007000": (0.04, 0.05),
    })
    mock_trading = MagicMock()
    mocker.patch("shared.alpaca_client.option_data", return_value=mock_opt)
    mocker.patch("shared.alpaca_client.trading", return_value=mock_trading)

    state = _spread_state_open(net_credit=50.0)
    mon.check_early_close(state)

    mock_trading.submit_order.assert_not_called()


def test_spread_mid_exactly_at_boundary_triggers_close(mocker):
    """When spread mid == exactly 50% of net credit (boundary), close is triggered."""
    import wheel.monitor as mon

    # net_credit = 50.0 → target = 0.25/share
    # short_bid=0.30, long_ask=0.05 → spread_mid = 0.25 == 0.25 → trigger (<=)
    mock_opt = _make_option_data_mock({
        "SOFI260529P00009000": (0.30, 0.32),
        "SOFI260529P00007000": (0.04, 0.05),
    })
    mock_trading = MagicMock()
    mocker.patch("shared.alpaca_client.option_data", return_value=mock_opt)
    mocker.patch("shared.alpaca_client.trading", return_value=mock_trading)

    state = _spread_state_open(net_credit=50.0)
    mon.check_early_close(state)

    mock_trading.submit_order.assert_called_once()


def test_spread_stage_not_open_is_skipped(mocker):
    """check_early_close for spread skips when stage != SPREAD_OPEN."""
    import wheel.monitor as mon

    mock_opt = MagicMock()
    mocker.patch("shared.alpaca_client.option_data", return_value=mock_opt)

    state = _spread_state_open()
    state["stage"] = "IDLE"
    mon.check_early_close(state)

    mock_opt.get_option_latest_quote.assert_not_called()


# ── Profit target from config (Fix #3) ───────────────────────────────────────

def test_custom_profit_target_pct_25_closes_at_75pct(mocker, monkeypatch):
    """WHEEL_PROFIT_TARGET_PCT=25 → monitor closes when mid ≤ 75% of net_credit.

    net_credit=50 → per-share=0.50; target=(1-0.25)*0.50=0.375/share
    short_bid=0.28, long_ask=0.05 → mid=0.23 <= 0.375 → trigger close.
    """
    monkeypatch.setenv("WHEEL_PROFIT_TARGET_PCT", "25")
    import wheel.monitor as mon

    mock_opt = _make_option_data_mock({
        "SOFI260529P00009000": (0.28, 0.32),
        "SOFI260529P00007000": (0.04, 0.05),
    })
    mock_trading = MagicMock()
    mocker.patch("shared.alpaca_client.option_data", return_value=mock_opt)
    mocker.patch("shared.alpaca_client.trading", return_value=mock_trading)

    state = _spread_state_open(net_credit=50.0)
    mon.check_early_close(state)

    # At 25% profit target: close when mid <= 0.375; mid=0.23 → should close
    mock_trading.submit_order.assert_called_once()


def test_custom_profit_target_pct_25_no_close_above_threshold(mocker, monkeypatch):
    """WHEEL_PROFIT_TARGET_PCT=25 → monitor does NOT close when mid > 75% of net_credit.

    net_credit=50 → per-share=0.50; target=(1-0.25)*0.50=0.375/share
    short_bid=0.44, long_ask=0.05 → mid=0.39 > 0.375 → no close.
    """
    monkeypatch.setenv("WHEEL_PROFIT_TARGET_PCT", "25")
    import wheel.monitor as mon

    mock_opt = _make_option_data_mock({
        "SOFI260529P00009000": (0.44, 0.46),
        "SOFI260529P00007000": (0.04, 0.05),
    })
    mock_trading = MagicMock()
    mocker.patch("shared.alpaca_client.option_data", return_value=mock_opt)
    mocker.patch("shared.alpaca_client.trading", return_value=mock_trading)

    state = _spread_state_open(net_credit=50.0)
    mon.check_early_close(state)

    # mid = 0.44 - 0.05 = 0.39 > 0.375 → no close
    mock_trading.submit_order.assert_not_called()


def test_default_profit_target_still_50pct(mocker, monkeypatch):
    """Default WHEEL_PROFIT_TARGET_PCT (50%) behavior is preserved (regression).

    net_credit=50 → per-share=0.50; target=0.50*0.50=0.25/share
    short_bid=0.30, long_ask=0.05 → mid=0.25 == 0.25 → trigger at boundary.
    """
    monkeypatch.delenv("WHEEL_PROFIT_TARGET_PCT", raising=False)
    import wheel.monitor as mon

    mock_opt = _make_option_data_mock({
        "SOFI260529P00009000": (0.30, 0.32),
        "SOFI260529P00007000": (0.04, 0.05),
    })
    mock_trading = MagicMock()
    mocker.patch("shared.alpaca_client.option_data", return_value=mock_opt)
    mocker.patch("shared.alpaca_client.trading", return_value=mock_trading)

    state = _spread_state_open(net_credit=50.0)
    mon.check_early_close(state)

    # At default 50%: mid=0.25 == target=0.25 → close
    mock_trading.submit_order.assert_called_once()


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
