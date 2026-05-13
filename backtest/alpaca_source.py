"""Alpaca-backed price source for the backtest fetcher.

Wraps the existing shared.alpaca_client.stock_data() to deliver historical daily
bars in the (date_iso, open, high, low, close) tuple format the fetcher expects.

A single call per ticker grabs the full window in one request; the fetcher
caches the result to disk, so subsequent runs never hit the API again.
"""
from __future__ import annotations
from datetime import datetime

from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from shared import alpaca_client


def fetch_bars(ticker: str, start: str, end: str):
    """Source callable for PriceFetcher. Returns list of price rows or [] on error."""
    try:
        client = alpaca_client.stock_data()
        resp = client.get_stock_bars(StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            start=datetime.strptime(start, "%Y-%m-%d"),
            end=datetime.strptime(end, "%Y-%m-%d"),
        ))
        bars = resp.data.get(ticker, [])
        return [
            (b.timestamp.strftime("%Y-%m-%d"),
             float(b.open), float(b.high), float(b.low), float(b.close))
            for b in bars
        ]
    except Exception as e:
        print(f"[ALPACA] fetch_bars({ticker}) failed: {type(e).__name__}: {e}")
        return []
