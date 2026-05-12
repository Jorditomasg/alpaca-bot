"""Unit tests for shared/kill_switch.py — global drawdown halt."""
from __future__ import annotations

import json
import pytest
from pathlib import Path
import shared.kill_switch as ks


@pytest.fixture(autouse=True)
def _isolated_state_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ks, "STATE_FILE", tmp_path / "kill_switch.json")
    monkeypatch.delenv("MAX_DRAWDOWN_PCT", raising=False)


# ── Initial state ───────────────────────────────────────────────────────────


def test_initial_state_has_no_peak_no_halt():
    s = ks.load()
    assert s["peak_equity"] is None
    assert s["halted"] is False


# ── Peak tracking ───────────────────────────────────────────────────────────


def test_first_update_sets_peak():
    s = ks.update(1000.0)
    assert s["peak_equity"] == 1000.0
    assert s["halted"] is False


def test_peak_advances_on_new_high():
    s = ks.update(1000.0)
    s = ks.update(1200.0, s)
    assert s["peak_equity"] == 1200.0


def test_peak_does_not_drop_on_dip():
    s = ks.update(1000.0)
    s = ks.update(1200.0, s)
    s = ks.update(1100.0, s)
    assert s["peak_equity"] == 1200.0


# ── Halt trigger ─────────────────────────────────────────────────────────────


def test_does_not_halt_at_19pct_dd():
    """19% drawdown is below the 20% default — must NOT halt."""
    s = ks.update(1000.0)
    s = ks.update(810.0, s)  # -19%
    assert s["halted"] is False


def test_halts_at_20pct_dd():
    """20% drawdown trips the kill switch."""
    s = ks.update(1000.0)
    s = ks.update(800.0, s)  # -20%
    assert s["halted"] is True
    assert s["halt_reason"] is not None


def test_halts_at_threshold_via_peak_not_current(monkeypatch):
    """DD is measured from peak, not from starting equity."""
    s = ks.update(1000.0)
    s = ks.update(2000.0, s)  # peak
    s = ks.update(1600.0, s)  # -20% from peak (but +60% from start)
    assert s["halted"] is True


def test_stays_halted_once_tripped():
    s = ks.update(1000.0)
    s = ks.update(800.0, s)
    assert s["halted"] is True
    # Equity recovers above peak — halt remains (must be manually reset)
    s = ks.update(1500.0, s)
    assert s["halted"] is True


def test_zero_or_negative_equity_does_not_trip():
    """Bad equity reading must not trip the switch."""
    s = ks.update(1000.0)
    s = ks.update(0.0, s)
    assert s["halted"] is False


# ── Env override ─────────────────────────────────────────────────────────────


def test_custom_max_drawdown_pct(monkeypatch):
    monkeypatch.setenv("MAX_DRAWDOWN_PCT", "0.10")
    s = ks.update(1000.0)
    s = ks.update(910.0, s)  # -9%
    assert s["halted"] is False
    s = ks.update(900.0, s)  # -10%
    assert s["halted"] is True


# ── Persistence ──────────────────────────────────────────────────────────────


def test_save_and_load_round_trip(tmp_path, monkeypatch):
    s = ks.update(1000.0)
    s = ks.update(800.0, s)
    ks.save(s)

    loaded = ks.load()
    assert loaded["halted"] is True
    assert loaded["peak_equity"] == 1000.0


def test_save_leaves_no_tmp_leak():
    s = ks.update(1000.0)
    ks.save(s)
    tmps = list(Path(ks.STATE_FILE).parent.glob(".kill_switch_*.tmp"))
    assert tmps == []


# ── is_halted / reason helpers ───────────────────────────────────────────────


def test_is_halted_returns_false_on_clean_state():
    assert ks.is_halted() is False


def test_is_halted_reflects_state_after_trip():
    s = ks.update(1000.0)
    s = ks.update(800.0, s)
    ks.save(s)
    assert ks.is_halted() is True
    assert ks.reason() is not None
