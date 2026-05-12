"""Unit tests for shared/trader.py — bar fetching + equity helpers."""
from __future__ import annotations

from unittest.mock import MagicMock
from shared import trader


def test_get_equity_returns_float(mocker):
    mock_client = MagicMock()
    mock_client.get_account.return_value = MagicMock(equity="12345.67")
    mocker.patch("shared.alpaca_client.trading", return_value=mock_client)

    assert trader.get_equity() == 12345.67


def test_get_recent_bars_returns_ohlc_dicts(mocker):
    """Adapter returns oldest-first list of {open, high, low, close, volume}."""
    fake_bars = [
        MagicMock(open=100.0, high=102.0, low=99.0, close=101.0, volume=1_000_000),
        MagicMock(open=101.0, high=103.0, low=100.5, close=102.5, volume=900_000),
    ]
    mock_resp = MagicMock(data={"AAPL": fake_bars})
    mock_client = MagicMock()
    mock_client.get_stock_bars.return_value = mock_resp
    mocker.patch("shared.alpaca_client.stock_data", return_value=mock_client)

    bars = trader.get_recent_bars("AAPL", days=30)
    assert len(bars) == 2
    assert bars[0]["close"] == 101.0
    assert bars[1]["high"] == 103.0
    assert set(bars[0].keys()) == {"open", "high", "low", "close", "volume"}


def test_get_recent_bars_returns_empty_on_failure(mocker, capsys):
    """API failure must return [] (caller handles fallback)."""
    mock_client = MagicMock()
    mock_client.get_stock_bars.side_effect = RuntimeError("rate limit")
    mocker.patch("shared.alpaca_client.stock_data", return_value=mock_client)

    bars = trader.get_recent_bars("AAPL", days=30)
    assert bars == []
    out = capsys.readouterr().out
    assert "failed" in out.lower()


def test_get_recent_bars_trims_to_requested_window(mocker):
    """When more bars come back than requested, trim to the most recent N."""
    fake_bars = [
        MagicMock(open=i, high=i + 1, low=i - 1, close=i, volume=1000)
        for i in range(100, 150)
    ]
    mock_resp = MagicMock(data={"AAPL": fake_bars})
    mock_client = MagicMock()
    mock_client.get_stock_bars.return_value = mock_resp
    mocker.patch("shared.alpaca_client.stock_data", return_value=mock_client)

    bars = trader.get_recent_bars("AAPL", days=10)
    assert len(bars) == 10
    # Most recent close == last fake bar's close == 149
    assert bars[-1]["close"] == 149
