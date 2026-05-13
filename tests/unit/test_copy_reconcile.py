"""Tests for copy_trader/reconcile.py — broker ↔ local state reconciliation."""
import pytest
from unittest.mock import MagicMock
from copy_trader import reconcile


def _broker_pos(symbol: str, qty: float = 1.0, avg_entry: float = 100.0):
    p = MagicMock()
    p.symbol = symbol
    p.qty = qty
    p.avg_entry_price = str(avg_entry)
    return p


def test_drops_state_positions_not_at_broker(mocker):
    """Phantoms from failed-order legacy state must be cleaned up at startup."""
    state = {"positions": {
        "AAPL":    {"notional": 250.0},
        "ETFIWD":  {"notional": 0.0},     # phantom — broker never opened it
        "PLCETN":  {"notional": 0.0},     # phantom
        "MSFT":    {"notional": 250.0},
    }}
    client = MagicMock()
    client.get_all_positions.return_value = [_broker_pos("AAPL"), _broker_pos("MSFT")]
    mocker.patch("shared.alpaca_client.trading", return_value=client)

    reconcile.with_broker(state)

    assert set(state["positions"].keys()) == {"AAPL", "MSFT"}


def test_keeps_state_positions_present_at_broker(mocker):
    state = {"positions": {"AAPL": {"notional": 250.0}}}
    client = MagicMock()
    client.get_all_positions.return_value = [_broker_pos("AAPL")]
    mocker.patch("shared.alpaca_client.trading", return_value=client)

    reconcile.with_broker(state)

    assert "AAPL" in state["positions"]


def test_no_op_when_broker_call_fails(mocker):
    """Network failure must not nuke local state. Fail-safe to keeping positions."""
    state = {"positions": {"AAPL": {"notional": 250.0}, "ETFIWD": {"notional": 0.0}}}
    client = MagicMock()
    client.get_all_positions.side_effect = ConnectionError("api down")
    mocker.patch("shared.alpaca_client.trading", return_value=client)

    reconcile.with_broker(state)

    assert set(state["positions"].keys()) == {"AAPL", "ETFIWD"}


def test_backfills_missing_cost_basis_from_broker(mocker):
    """Legacy positions without entry metadata get backfilled from broker
    avg_entry_price so the exits module can evaluate them."""
    state = {"positions": {"AAPL": {"notional": 250.0}}}  # no cost_basis/entry_date
    client = MagicMock()
    client.get_all_positions.return_value = [_broker_pos("AAPL", avg_entry=180.0)]
    mocker.patch("shared.alpaca_client.trading", return_value=client)

    reconcile.with_broker(state)

    pos = state["positions"]["AAPL"]
    assert pos["cost_basis"] == 180.0
    assert pos["high_watermark"] >= 180.0
    assert "entry_date" in pos  # some date stamped


def test_does_not_overwrite_existing_cost_basis(mocker):
    """If we already track entry data, broker's avg_entry doesn't override."""
    state = {"positions": {"AAPL": {
        "notional": 250.0,
        "entry_date": "2026-01-01",
        "cost_basis": 150.0,
        "high_watermark": 200.0,
    }}}
    client = MagicMock()
    client.get_all_positions.return_value = [_broker_pos("AAPL", avg_entry=180.0)]
    mocker.patch("shared.alpaca_client.trading", return_value=client)

    reconcile.with_broker(state)

    pos = state["positions"]["AAPL"]
    assert pos["cost_basis"] == 150.0
    assert pos["entry_date"] == "2026-01-01"
