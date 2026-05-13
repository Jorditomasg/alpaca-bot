"""Unit tests for copy_trader/copier.py — switch-safety + option translation."""
import pytest
import copy_trader.copier as copier


# ── Bug 2 regression: politician switch must not dump history ───────────────


def test_seed_seen_ids_marks_all_visible_trades_of_new_following():
    """On politician switch, currently visible trades of the new top must be
    marked as already-seen so we only copy trades that appear AFTER the switch."""
    trades = [
        {"id": "g1", "politician": "Gary Peters", "ticker": "AAPL", "type": "buy"},
        {"id": "b1", "politician": "John Boozman", "ticker": "WFC",  "type": "buy"},
        {"id": "b2", "politician": "John Boozman", "ticker": "MSFT", "type": "buy"},
        {"id": "b3", "politician": "John Boozman", "ticker": "HD",   "type": "buy"},
    ]
    state = {"seen_trade_ids": ["g1"]}

    copier.seed_seen_ids_for(state, trades, "John Boozman")

    assert "b1" in state["seen_trade_ids"]
    assert "b2" in state["seen_trade_ids"]
    assert "b3" in state["seen_trade_ids"]
    # Pre-existing IDs preserved
    assert "g1" in state["seen_trade_ids"]


def test_seed_seen_ids_is_idempotent():
    """Calling seed twice must not duplicate IDs."""
    trades = [
        {"id": "b1", "politician": "John Boozman", "ticker": "WFC", "type": "buy"},
    ]
    state = {"seen_trade_ids": []}

    copier.seed_seen_ids_for(state, trades, "John Boozman")
    copier.seed_seen_ids_for(state, trades, "John Boozman")

    assert state["seen_trade_ids"].count("b1") == 1


def test_seed_then_copy_returns_empty():
    """End-to-end: after seeding, new_trades_to_copy returns nothing — until a
    genuinely new trade appears."""
    visible = [
        {"id": "b1", "politician": "John Boozman", "ticker": "WFC",  "type": "buy"},
        {"id": "b2", "politician": "John Boozman", "ticker": "MSFT", "type": "buy"},
    ]
    state = {"seen_trade_ids": []}
    copier.seed_seen_ids_for(state, visible, "John Boozman")

    assert copier.new_trades_to_copy(visible, "John Boozman", state["seen_trade_ids"]) == []

    # New trade appears later
    visible_plus = visible + [
        {"id": "b3", "politician": "John Boozman", "ticker": "GOOGL", "type": "buy"},
    ]
    result = copier.new_trades_to_copy(visible_plus, "John Boozman", state["seen_trade_ids"])
    assert len(result) == 1
    assert result[0]["id"] == "b3"


# ── Bug 1 redux + improvement A: pub_date freshness + min_amount filters ────


def test_freshness_filter_drops_stale_filings():
    """Trades published more than N days ago are stale signals — skip."""
    trades = [
        # Stale: filed 60 days ago
        {"id": "t1", "politician": "John Boozman", "ticker": "WFC", "type": "buy",
         "pub_date": "2026-03-14", "amount_mid": 50000},
        # Fresh: filed yesterday
        {"id": "t2", "politician": "John Boozman", "ticker": "MSFT", "type": "buy",
         "pub_date": "2026-05-12", "amount_mid": 50000},
    ]
    out = copier.new_trades_to_copy(
        trades, "John Boozman", seen_ids=[],
        today="2026-05-13", freshness_days=30,
    )
    assert [t["ticker"] for t in out] == ["MSFT"]


def test_min_amount_filter_drops_small_dollar_trades():
    """Politician trades below the min-amount threshold are noise."""
    trades = [
        # Small: $1K-15K range → mid $8K → below $15k threshold
        {"id": "t1", "politician": "John Boozman", "ticker": "WFC", "type": "buy",
         "pub_date": "2026-05-12", "amount_mid": 8000},
        # Large: $50K-100K → mid $75K
        {"id": "t2", "politician": "John Boozman", "ticker": "MSFT", "type": "buy",
         "pub_date": "2026-05-12", "amount_mid": 75000},
    ]
    out = copier.new_trades_to_copy(
        trades, "John Boozman", seen_ids=[],
        today="2026-05-13", min_amount=15000,
    )
    assert [t["ticker"] for t in out] == ["MSFT"]


def test_sells_bypass_min_amount_filter():
    """SELL signals must always pass — exiting a position cannot be filtered out
    just because the politician's sell ticket happens to be small."""
    trades = [
        {"id": "t1", "politician": "John Boozman", "ticker": "WFC", "type": "sell",
         "pub_date": "2026-05-12", "amount_mid": 1000},
    ]
    out = copier.new_trades_to_copy(
        trades, "John Boozman", seen_ids=[],
        today="2026-05-13", min_amount=15000,
    )
    assert len(out) == 1
    assert out[0]["type"] == "sell"


def test_filters_default_to_no_op_when_today_not_provided():
    """Backwards compat: existing callers without filter args see no behavior change."""
    trades = [
        {"id": "t1", "politician": "John Boozman", "ticker": "WFC", "type": "buy",
         "pub_date": "2020-01-01", "amount_mid": 100},
    ]
    out = copier.new_trades_to_copy(trades, "John Boozman", seen_ids=[])
    assert len(out) == 1
