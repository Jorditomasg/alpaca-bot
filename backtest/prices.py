"""Historical price fetcher with on-disk cache.

The fetcher is parametric on `source` — a callable `(ticker, start, end) -> list
of (date, open, high, low, close)`. Production passes the Alpaca-backed source.
Tests pass fakes.

Cache layout: one JSON file per ticker under `cache_dir/`. Once a ticker is
cached, subsequent runs read it instead of hitting the source — which makes
repeat backtest runs near-instant.
"""
from __future__ import annotations
import bisect
import json
import pathlib
from datetime import datetime, timedelta
from typing import Callable

# (date_iso, open, high, low, close)
PriceRow = tuple[str, float, float, float, float]
PriceSource = Callable[[str, str, str], list[PriceRow]]

# How far forward we'll walk when a requested date has no bar (weekend, holiday).
_FORWARD_WALK_LIMIT = 7


class PriceFetcher:
    def __init__(
        self,
        cache_dir: pathlib.Path,
        source: PriceSource,
        history_start: str = "2012-01-01",
        history_end: str = "2021-12-31",
    ) -> None:
        self._cache_dir = pathlib.Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._source = source
        self._history_start = history_start
        self._history_end = history_end
        self._mem: dict[str, list[PriceRow]] = {}

    def get_close_on(self, ticker: str, date_iso: str) -> float | None:
        """Return the closing price for `ticker` on `date_iso`.

        If the date is a weekend / holiday, walks forward up to a week to find
        the next trading day. Returns None if no data is available.
        """
        bars = self._bars_for(ticker)
        if not bars:
            return None

        # Bars are sorted ascending by date string (ISO format sorts correctly).
        idx = bisect.bisect_left([b[0] for b in bars], date_iso)
        if idx >= len(bars):
            return None

        # Walk forward up to a few days if exact date missing.
        target = datetime.strptime(date_iso, "%Y-%m-%d")
        for offset in range(_FORWARD_WALK_LIMIT):
            check_iso = (target + timedelta(days=offset)).strftime("%Y-%m-%d")
            if idx < len(bars) and bars[idx][0] == check_iso:
                return bars[idx][4]
            if idx < len(bars) and bars[idx][0] < check_iso:
                idx += 1
                continue
        # Fall through: use whatever the next bar at idx is, as long as within window
        if idx < len(bars):
            bar_date = datetime.strptime(bars[idx][0], "%Y-%m-%d")
            if (bar_date - target).days <= _FORWARD_WALK_LIMIT:
                return bars[idx][4]
        return None

    def _bars_for(self, ticker: str) -> list[PriceRow]:
        if ticker in self._mem:
            return self._mem[ticker]

        cache_file = self._cache_dir / f"{ticker}.json"
        if cache_file.exists():
            data = json.loads(cache_file.read_text())
            bars = [tuple(row) for row in data]
        else:
            bars = self._source(ticker, self._history_start, self._history_end) or []
            cache_file.write_text(json.dumps(bars))

        self._mem[ticker] = bars
        return bars
