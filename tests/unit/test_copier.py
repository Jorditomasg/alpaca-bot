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
