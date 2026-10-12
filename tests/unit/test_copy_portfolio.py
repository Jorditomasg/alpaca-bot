"""Tests for copy_trader/portfolio.py — fixed-notional sizing, handled-trades
contract, position metadata, close-and-remove."""
import pytest
from unittest.mock import MagicMock
from copy_trader import portfolio


# ── execute_batch: fixed notional from equity, no rebalancing ────────────────


def _buy(ticker: str, tid: str = "t1") -> dict:
    return {"id": tid, "ticker": ticker, "type": "buy"}


def _sell(ticker: str, tid: str = "t2") -> dict:
    return {"id": tid, "ticker": ticker, "type": "sell"}


def _mock_broker(mocker, equity=1000.0, buying_power="500", price=10.0):
    client = MagicMock()
    client.get_account.return_value = MagicMock(buying_power=buying_power)
    mocker.patch("shared.alpaca_client.trading", return_value=client)
    mocker.patch("shared.trader.get_equity", return_value=equity)
    mocker.patch("shared.trader.get_latest_price", return_value=price)
    buy = mocker.patch("shared.trader.buy")
    return client, buy


def test_buy_opens_fixed_notional_position(mocker, monkeypatch):
    """A new buy is sized at NOTIONAL_PCT% of equity, not buying_power/n."""
    monkeypatch.setattr(portfolio.config, "NOTIONAL_PCT", 5.0)
    _, buy = _mock_broker(mocker, equity=1000.0, buying_power="500", price=10.0)
    state = {"positions": {}}

    handled = portfolio.execute_batch([_buy("AAPL")], state)

    buy.assert_called_once_with("AAPL", notional=50.0)
    assert [t["ticker"] for t in handled] == ["AAPL"]
    pos = state["positions"]["AAPL"]
    assert pos["notional"] == 50.0
    assert pos["cost_basis"] == 10.0


def test_buy_not_handled_when_buying_power_insufficient(mocker, monkeypatch):
    """BP below the notional → buy skipped AND not handled (caller retries)."""
    monkeypatch.setattr(portfolio.config, "NOTIONAL_PCT", 5.0)
    _, buy = _mock_broker(mocker, equity=1000.0, buying_power="20")
    state = {"positions": {}}

    handled = portfolio.execute_batch([_buy("AAPL")], state)

    buy.assert_not_called()
    assert handled == []
    assert state["positions"] == {}


# ── Concentration controls: max positions + deployment ceiling ───────────────


def _positions(n: int) -> dict:
    """n filler open positions so count-based caps can be exercised."""
    return {
        f"SYM{i}": {"notional": 50.0, "entry_date": "2026-05-01",
                    "cost_basis": 10.0, "high_watermark": 10.0}
        for i in range(n)
    }


def test_buy_skipped_at_max_positions(mocker, monkeypatch):
    """At the position cap, a new buy is NOT opened and NOT handled (retry later)."""
    monkeypatch.setattr(portfolio.config, "NOTIONAL_PCT", 5.0)
    monkeypatch.setattr(portfolio.config, "MAX_POSITIONS", 8)
    monkeypatch.setattr(portfolio.config, "MAX_INVESTED_PCT", 80.0)
    # Plenty of buying power and deployment room — only the count cap should bind.
    _, buy = _mock_broker(mocker, equity=1000.0, buying_power="900")
    state = {"positions": _positions(8)}

    handled = portfolio.execute_batch([_buy("AAPL")], state)

    buy.assert_not_called()
    assert handled == []
    assert "AAPL" not in state["positions"]


def test_buy_allowed_one_slot_below_max_positions(mocker, monkeypatch):
    """A free slot under the cap still opens normally."""
    monkeypatch.setattr(portfolio.config, "NOTIONAL_PCT", 5.0)
    monkeypatch.setattr(portfolio.config, "MAX_POSITIONS", 8)
    monkeypatch.setattr(portfolio.config, "MAX_INVESTED_PCT", 80.0)
    _, buy = _mock_broker(mocker, equity=1000.0, buying_power="900")
    state = {"positions": _positions(7)}

    handled = portfolio.execute_batch([_buy("AAPL")], state)

    buy.assert_called_once()
    assert "AAPL" in state["positions"]


def test_max_positions_never_blocks_a_sell(mocker, monkeypatch):
    """Exits must always run even when the book is at the position cap."""
    monkeypatch.setattr(portfolio.config, "NOTIONAL_PCT", 5.0)
    monkeypatch.setattr(portfolio.config, "MAX_POSITIONS", 8)
    client, _ = _mock_broker(mocker, equity=1000.0, buying_power="900")
    positions = _positions(8)
    positions["SYM0"]  # SYM0 is held; selling it must work despite the cap
    state = {"positions": positions}

    handled = portfolio.execute_batch([_sell("SYM0")], state)

    client.close_position.assert_called_once_with("SYM0")
    assert "SYM0" not in state["positions"]
    assert [t["ticker"] for t in handled] == ["SYM0"]


def test_buy_skipped_when_deployment_ceiling_reached(mocker, monkeypatch):
    """Already deployed past MAX_INVESTED_PCT of equity → new buy skipped, not handled.

    equity=1000, bp=100 → invested≈900 > 80% ceiling (800). Buying power alone
    ($100) would allow the $50 buy; only the deployment ceiling stops it.
    """
    monkeypatch.setattr(portfolio.config, "NOTIONAL_PCT", 5.0)
    monkeypatch.setattr(portfolio.config, "MAX_POSITIONS", 99)
    monkeypatch.setattr(portfolio.config, "MAX_INVESTED_PCT", 80.0)
    _, buy = _mock_broker(mocker, equity=1000.0, buying_power="100")
    state = {"positions": _positions(1)}

    handled = portfolio.execute_batch([_buy("AAPL")], state)

    buy.assert_not_called()
    assert handled == []


def test_batch_stops_buying_when_running_deployment_ceiling_hit(mocker, monkeypatch):
    """Within one batch, buys stop once cumulative deployment hits the ceiling.

    equity=1000, bp=320 → invested=680, ceiling 80%→800, room=120. At $50 each,
    exactly 2 buys fit (100 ≤ 120); the 3rd would breach the ceiling.
    """
    monkeypatch.setattr(portfolio.config, "NOTIONAL_PCT", 5.0)
    monkeypatch.setattr(portfolio.config, "MAX_POSITIONS", 99)
    monkeypatch.setattr(portfolio.config, "MAX_INVESTED_PCT", 80.0)
    _, buy = _mock_broker(mocker, equity=1000.0, buying_power="320")
    state = {"positions": {}}

    handled = portfolio.execute_batch(
        [_buy("AAA", "t1"), _buy("BBB", "t2"), _buy("CCC", "t3")], state
    )

    assert buy.call_count == 2
    assert [t["id"] for t in handled] == ["t1", "t2"]
    assert set(state["positions"]) == {"AAA", "BBB"}


def test_existing_positions_are_never_resized(mocker, monkeypatch):
    """A new signal must not generate orders against already-open positions —
    the old rebalance-to-buying_power/n behavior shrank the whole portfolio."""
    monkeypatch.setattr(portfolio.config, "NOTIONAL_PCT", 5.0)
    client, buy = _mock_broker(mocker, equity=1000.0, buying_power="500")
    state = {"positions": {
        "WFC": {"notional": 80.0, "entry_date": "2026-05-01",
                "cost_basis": 70.0, "high_watermark": 75.0},
    }}

    portfolio.execute_batch([_buy("AAPL")], state)

    buy.assert_called_once()  # only the new ticker
    assert buy.call_args[0][0] == "AAPL"
    client.submit_order.assert_not_called()  # no direct resize orders either
    assert state["positions"]["WFC"]["notional"] == 80.0


def test_buy_for_already_open_ticker_is_handled_without_order(mocker, monkeypatch):
    monkeypatch.setattr(portfolio.config, "NOTIONAL_PCT", 5.0)
    _, buy = _mock_broker(mocker)
    state = {"positions": {
        "AAPL": {"notional": 50.0, "entry_date": "2026-05-01",
                 "cost_basis": 9.0, "high_watermark": 9.5},
    }}

    handled = portfolio.execute_batch([_buy("AAPL")], state)

    buy.assert_not_called()
    assert [t["ticker"] for t in handled] == ["AAPL"]
    assert state["positions"]["AAPL"]["cost_basis"] == 9.0  # metadata untouched


def test_sell_of_unheld_ticker_is_handled_without_broker_call(mocker, monkeypatch):
    monkeypatch.setattr(portfolio.config, "NOTIONAL_PCT", 5.0)
    client, _ = _mock_broker(mocker)
    state = {"positions": {}}

    handled = portfolio.execute_batch([_sell("TSLA")], state)

    client.close_position.assert_not_called()
    assert [t["ticker"] for t in handled] == ["TSLA"]


def test_sell_of_held_ticker_closes_and_is_handled(mocker, monkeypatch):
    monkeypatch.setattr(portfolio.config, "NOTIONAL_PCT", 5.0)
    client, _ = _mock_broker(mocker)
    state = {"positions": {
        "TSLA": {"notional": 50.0, "entry_date": "2026-05-01",
                 "cost_basis": 200.0, "high_watermark": 210.0},
    }}

    handled = portfolio.execute_batch([_sell("TSLA")], state)

    client.close_position.assert_called_once_with("TSLA")
    assert "TSLA" not in state["positions"]
    assert [t["ticker"] for t in handled] == ["TSLA"]


def test_equity_unavailable_skips_buys_but_sells_still_handled(mocker, monkeypatch):
    """No equity figure (API down, no fallback) → buys retried later; sells
    must still execute — an exit signal is never deferred."""
    monkeypatch.setattr(portfolio.config, "NOTIONAL_PCT", 5.0)
    client = MagicMock()
    mocker.patch("shared.alpaca_client.trading", return_value=client)
    mocker.patch("shared.trader.get_equity", side_effect=RuntimeError("api down"))
    buy = mocker.patch("shared.trader.buy")
    state = {"positions": {
        "TSLA": {"notional": 50.0, "entry_date": "2026-05-01",
                 "cost_basis": 200.0, "high_watermark": 210.0},
    }}

    handled = portfolio.execute_batch(
        [_buy("AAPL", "t1"), _sell("TSLA", "t2")], state
    )

    buy.assert_not_called()
    client.close_position.assert_called_once_with("TSLA")
    assert [t["id"] for t in handled] == ["t2"]


# ── Metadata stamping on new position ───────────────────────────────────────


def test_stamp_open_creates_position_with_metadata():
    positions: dict = {}

    portfolio._stamp_open(positions, "AAPL", today="2026-05-13", fill_price=180.5)

    pos = positions["AAPL"]
    assert pos["notional"] == 0.0
    assert pos["entry_date"] == "2026-05-13"
    assert pos["cost_basis"] == 180.5
    assert pos["high_watermark"] == 180.5


def test_stamp_open_idempotent_when_position_exists():
    """Re-opening should NOT overwrite existing metadata (cost basis would shift)."""
    positions = {"AAPL": {
        "notional": 250.0, "entry_date": "2026-01-01",
        "cost_basis": 150.0, "high_watermark": 200.0,
    }}

    portfolio._stamp_open(positions, "AAPL", today="2026-05-13", fill_price=180.5)

    assert positions["AAPL"]["entry_date"] == "2026-01-01"
    assert positions["AAPL"]["cost_basis"] == 150.0
    assert positions["AAPL"]["high_watermark"] == 200.0


# ── Close + remove ──────────────────────────────────────────────────────────


def test_close_and_remove_drops_from_state_and_calls_broker(mocker):
    positions = {"AAPL": {"notional": 250.0, "entry_date": "2026-05-01",
                          "cost_basis": 180.0, "high_watermark": 200.0}}
    state = {"positions": positions}

    client = MagicMock()
    mocker.patch("shared.alpaca_client.trading", return_value=client)

    portfolio.close_and_remove("AAPL", state)

    assert "AAPL" not in positions
    client.close_position.assert_called_once_with("AAPL")


def test_close_and_remove_no_op_when_position_missing(mocker):
    state = {"positions": {}}
    client = MagicMock()
    mocker.patch("shared.alpaca_client.trading", return_value=client)

    portfolio.close_and_remove("AAPL", state)  # should not raise

    client.close_position.assert_not_called()


# ── Kill switch: halted means no NEW risk, never a blocked exit ──────────────
#
# 2026-08-15 audit. shared/kill_switch.py says it is "designed to be queried by
# every strategy", and wheel/engine.py and the trailing entry both do. The copy
# strategy — the only one that actually held positions — never asked. A -20%
# account drawdown halted the wheel and left copy free to keep opening names.


def test_halted_kill_switch_blocks_new_buys(mocker, monkeypatch):
    monkeypatch.setattr(portfolio.config, "NOTIONAL_PCT", 5.0)
    _, buy = _mock_broker(mocker, equity=1000.0, buying_power="500", price=10.0)
    state = {"positions": {}}

    handled = portfolio.execute_batch([_buy("AAPL")], state, halted=True)

    buy.assert_not_called()
    assert state["positions"] == {}


def test_a_buy_blocked_by_the_kill_switch_is_not_marked_handled(mocker, monkeypatch):
    """Same contract as every other skip: the filing must stay retryable while
    it is fresh, so the position opens as soon as the halt clears."""
    monkeypatch.setattr(portfolio.config, "NOTIONAL_PCT", 5.0)
    _mock_broker(mocker, equity=1000.0, buying_power="500", price=10.0)
    state = {"positions": {}}

    handled = portfolio.execute_batch([_buy("AAPL")], state, halted=True)

    assert handled == []


def test_halted_kill_switch_still_lets_sells_through(mocker, monkeypatch):
    """Exits are never gated — a halt must leave risk managed, not frozen."""
    client, _ = _mock_broker(mocker, equity=1000.0, buying_power="500", price=10.0)
    state = {"positions": {"AAPL": {"notional": 50.0, "cost_basis": 10.0,
                                    "entry_date": "2026-01-01",
                                    "high_watermark": 10.0}}}

    handled = portfolio.execute_batch([_sell("AAPL")], state, halted=True)

    client.close_position.assert_called_once_with("AAPL")
    assert state["positions"] == {}
    assert [t["ticker"] for t in handled] == ["AAPL"]


def test_not_halted_is_the_default_and_behaves_as_before(mocker, monkeypatch):
    monkeypatch.setattr(portfolio.config, "NOTIONAL_PCT", 5.0)
    _, buy = _mock_broker(mocker, equity=1000.0, buying_power="500", price=10.0)
    state = {"positions": {}}

    handled = portfolio.execute_batch([_buy("AAPL")], state)

    buy.assert_called_once_with("AAPL", notional=50.0)
    assert [t["ticker"] for t in handled] == ["AAPL"]


def _order(order_id: str, symbol):
    o = MagicMock()
    o.id = order_id
    o.symbol = symbol
    return o


def test_closing_a_copy_position_never_cancels_another_strategys_multileg_order(mocker):
    # Incident 2026-09-22: Alpaca's `symbols=[V]` filter also returned the wheel's
    # SOFI multi-leg profit-take (mleg orders carry symbol=None). Closing V
    # cancelled it and the spread was left open into expiry week.
    state = {"positions": {"V": {"notional": 250.0, "entry_date": "2026-09-01",
                                 "cost_basis": 300.0, "high_watermark": 320.0}}}
    client = MagicMock()
    client.get_orders.return_value = [
        _order("own-stop", "V"),
        _order("wheel-mleg", None),
        _order("other", "SOFI260925P00017500"),
    ]
    mocker.patch("shared.alpaca_client.trading", return_value=client)

    portfolio.close_and_remove("V", state)

    client.cancel_order_by_id.assert_called_once_with("own-stop")
    client.close_position.assert_called_once_with("V")


# ── A failed broker close must not drop the position from local state ───────
# Regression: close_position swallowed the error and callers popped the
# position anyway, leaving shares at the broker that no exit rule watched.


def test_failed_close_keeps_position_and_leaves_sell_unhandled(mocker, monkeypatch):
    monkeypatch.setattr(portfolio.config, "NOTIONAL_PCT", 5.0)
    client, _ = _mock_broker(mocker)
    client.close_position.side_effect = RuntimeError("HTTP 500")
    state = {"positions": {
        "TSLA": {"notional": 50.0, "entry_date": "2026-05-01",
                 "cost_basis": 200.0, "high_watermark": 210.0},
    }}

    handled = portfolio.execute_batch([_sell("TSLA")], state)

    assert "TSLA" in state["positions"]  # still tracked → retried next cycle
    assert handled == []


def test_close_and_remove_keeps_position_on_failure(mocker):
    client, _ = _mock_broker(mocker)
    client.close_position.side_effect = RuntimeError("HTTP 500")
    state = {"positions": {"PG": {"notional": 27.0, "entry_date": "2026-05-13",
                                  "cost_basis": 144.0, "high_watermark": 150.0}}}

    portfolio.close_and_remove("PG", state)

    assert "PG" in state["positions"]


def test_close_of_position_already_gone_at_broker_drops_it(mocker):
    """Broker says the position does not exist → nothing left to close; drop
    it instead of retrying forever."""
    client, _ = _mock_broker(mocker)
    client.close_position.side_effect = RuntimeError(
        '{"code":40410000,"message":"position does not exist"}'
    )
    state = {"positions": {"PG": {"notional": 27.0, "entry_date": "2026-05-13",
                                  "cost_basis": 144.0, "high_watermark": 150.0}}}

    portfolio.close_and_remove("PG", state)

    assert "PG" not in state["positions"]
