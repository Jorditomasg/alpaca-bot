"""Tests for copy_trader/portfolio.py — position metadata + close-and-remove."""
import pytest
from unittest.mock import MagicMock
from copy_trader import portfolio


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
