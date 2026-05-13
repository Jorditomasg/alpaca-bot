"""Tests for backtest/data.py — PTR JSON loader and normalizer."""
import json
import pathlib
import pytest
from backtest import data as bt_data


FIXTURE = pathlib.Path(__file__).parent.parent / "fixtures" / "ptr_sample.json"


def test_load_normalizes_stock_purchase_to_buy():
    trades = bt_data.load_ptrs(FIXTURE)

    aapl = next(t for t in trades if t["ticker"] == "AAPL")
    assert aapl["type"] == "buy"
    assert aapl["politician"] == "Jane Doe"
    assert aapl["traded_date"] == "2020-11-10"
    assert aapl["amount_low"] == 15001
    assert aapl["amount_high"] == 50000
    assert aapl["amount_mid"] == pytest.approx(32500.5)


def test_load_normalizes_sale_full_to_sell():
    trades = bt_data.load_ptrs(FIXTURE)

    msft = next(t for t in trades if t["ticker"] == "MSFT")
    assert msft["type"] == "sell"


def test_load_filters_non_stock_assets():
    """Bonds, options, mutual funds — not in scope for stock backtest."""
    trades = bt_data.load_ptrs(FIXTURE)

    tickers = [t["ticker"] for t in trades]
    assert "US10Y" not in tickers


def test_load_simulates_pub_date_30_days_after_trade():
    """STOCK Act: disclosure within 45d. We use 30d as realistic average."""
    trades = bt_data.load_ptrs(FIXTURE)

    aapl = next(t for t in trades if t["ticker"] == "AAPL")
    # traded 2020-11-10 → pub 2020-12-10
    assert aapl["pub_date"] == "2020-12-10"


def test_load_assigns_stable_ids():
    """Each trade gets a unique stable id (so seen_trade_ids works)."""
    trades = bt_data.load_ptrs(FIXTURE)

    ids = [t["id"] for t in trades]
    assert len(ids) == len(set(ids))


def test_load_skips_malformed_dates():
    """A bad date row must be dropped without crashing the whole load."""
    trades = bt_data.load_ptrs(FIXTURE)

    # The BAD-DATE row has a valid date — let's actually verify with a row that
    # would fail. Make a synthetic test:
    import tempfile
    bad = [{
        "transaction_date": "not-a-date",
        "owner": "Self",
        "ticker": "BAD",
        "asset_description": "x",
        "asset_type": "Stock",
        "type": "Purchase",
        "amount": "$1,001 - $15,000",
        "comment": "--",
        "senator": "X Y",
        "ptr_link": "https://example.com/bad/",
    }]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(bad, f)
        tmp_path = f.name

    out = bt_data.load_ptrs(pathlib.Path(tmp_path))
    assert out == []
