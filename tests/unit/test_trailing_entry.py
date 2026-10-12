"""Trailing entry selection — never buy without a consensus signal.

Regression (2026-10-01 14:32 UTC): the scraper returned 0 trades, the entry
fell back to a hardcoded "TSLA" and bought 30 % of buying power on no signal.
Flagged in docs/2026-08-15-trading-audit.md and never fixed until it fired.
"""
import asyncio
import os
from unittest.mock import MagicMock, patch

# scheduler calls load_dotenv() at import, which would leak the real .env into
# the process and break tests that assert config defaults. Import it with
# load_dotenv neutralised and the environment restored afterwards.
_env_before = dict(os.environ)
with patch("dotenv.load_dotenv", lambda *a, **k: False):
    import scheduler
os.environ.clear()
os.environ.update(_env_before)


def _patch_common(monkeypatch, trades, consensus):
    monkeypatch.setattr(scheduler, "_refresh_kill_switch", lambda: False)
    monkeypatch.setattr(scheduler.scraper, "fetch_trades", lambda *a, **k: trades)
    monkeypatch.setattr(scheduler.scorer, "get_consensus_ticker", lambda t: consensus)
    trader = MagicMock()
    trader.get_buying_power.return_value = 1000.0
    monkeypatch.setattr(scheduler, "shared_trader", trader)
    return trader


def test_no_consensus_skips_entry_instead_of_buying_tsla(monkeypatch):
    trader = _patch_common(monkeypatch, trades=[], consensus=None)

    result = asyncio.run(scheduler._open_trailing_position())

    assert result is None
    trader.buy.assert_not_called()


def test_scraper_exception_skips_entry(monkeypatch):
    trader = _patch_common(monkeypatch, trades=[], consensus=None)

    def boom(*a, **k):
        raise RuntimeError("HTTP 429")

    monkeypatch.setattr(scheduler.scraper, "fetch_trades", boom)

    result = asyncio.run(scheduler._open_trailing_position())

    assert result is None
    trader.buy.assert_not_called()
