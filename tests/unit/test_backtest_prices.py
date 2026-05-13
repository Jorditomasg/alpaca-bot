"""Tests for backtest/prices.py — price fetcher with disk cache."""
from __future__ import annotations
import pathlib
import pytest
from backtest import prices as bt_prices


def test_get_close_on_returns_close_from_loaded_bars(tmp_path):
    """Given a ticker with bars in cache, get_close_on returns close price."""
    fetcher = bt_prices.PriceFetcher(cache_dir=tmp_path, source=_fake_source({
        "AAPL": [
            ("2020-11-10", 100.0, 105.0, 99.0, 104.0),
            ("2020-11-11", 104.5, 107.0, 103.0, 106.5),
        ],
    }))

    assert fetcher.get_close_on("AAPL", "2020-11-10") == 104.0
    assert fetcher.get_close_on("AAPL", "2020-11-11") == 106.5


def test_get_close_on_walks_forward_when_date_is_weekend(tmp_path):
    """If date falls on a weekend / market-closed day, return the next open day."""
    fetcher = bt_prices.PriceFetcher(cache_dir=tmp_path, source=_fake_source({
        "MSFT": [
            ("2020-11-06", 200.0, 202.0, 199.0, 201.0),  # Fri
            ("2020-11-09", 203.0, 205.0, 202.0, 204.0),  # Mon
        ],
    }))

    # 2020-11-07 = Sat, 2020-11-08 = Sun → walk forward to Mon close
    assert fetcher.get_close_on("MSFT", "2020-11-07") == 204.0


def test_get_close_on_returns_none_when_no_data_available(tmp_path):
    fetcher = bt_prices.PriceFetcher(cache_dir=tmp_path, source=_fake_source({}))
    assert fetcher.get_close_on("UNKNOWN", "2020-11-10") is None


def test_cache_persists_across_fetcher_instances(tmp_path):
    """First fetcher hits the source; second one reuses the cache file."""
    source_calls = {"n": 0}

    def counting_source(ticker, start, end):
        source_calls["n"] += 1
        return [("2020-11-10", 100.0, 105.0, 99.0, 104.0)]

    f1 = bt_prices.PriceFetcher(cache_dir=tmp_path, source=counting_source)
    assert f1.get_close_on("AAPL", "2020-11-10") == 104.0
    assert source_calls["n"] == 1

    # New instance, same cache dir → no new source call
    f2 = bt_prices.PriceFetcher(cache_dir=tmp_path, source=counting_source)
    assert f2.get_close_on("AAPL", "2020-11-10") == 104.0
    assert source_calls["n"] == 1


def _fake_source(by_ticker: dict):
    def src(ticker, start, end):
        return by_ticker.get(ticker, [])
    return src
