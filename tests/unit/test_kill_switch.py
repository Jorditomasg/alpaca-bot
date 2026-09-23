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
    """20% drawdown, sustained across CONFIRMATIONS samples, trips the switch."""
    s = ks.update(1000.0)
    for _ in range(ks._confirmations()):
        s = ks.update(800.0, s)  # -20%
    assert s["halted"] is True
    assert s["halt_reason"] is not None


def test_halts_at_threshold_via_peak_not_current(monkeypatch):
    """DD is measured from peak, not from starting equity."""
    s = ks.update(1000.0)
    s = ks.update(2000.0, s)  # peak
    for _ in range(ks._confirmations()):
        s = ks.update(1600.0, s)  # -20% from peak (but +60% from start)
    assert s["halted"] is True


def test_zero_or_negative_equity_does_not_trip():
    """Bad equity reading must not trip the switch."""
    s = ks.update(1000.0)
    s = ks.update(0.0, s)
    assert s["halted"] is False


# ── Glitch rejection ─────────────────────────────────────────────────────────
#
# 2026-07-30 incident: a single phantom equity read of $607.80 latched the halt
# on the live paper account while Alpaca's own portfolio history showed equity
# never left the $1000–$1084 band. The wheel strategy sat dead for days.


def test_single_bad_sample_does_not_halt():
    s = ks.update(1000.0)
    s = ks.update(400.0, s)  # -60% glitch
    assert s["halted"] is False
    assert s["breach_streak"] == 1


def test_breach_streak_resets_when_equity_reads_healthy_again():
    s = ks.update(1000.0)
    s = ks.update(400.0, s)   # glitch
    s = ks.update(1010.0, s)  # real value
    assert s["breach_streak"] == 0
    assert s["halted"] is False


def test_isolated_glitches_never_accumulate_into_a_halt():
    """Alternating glitch/healthy reads must not add up to a trip."""
    s = ks.update(1000.0)
    for _ in range(10):
        s = ks.update(607.80, s)
        s = ks.update(1061.92, s)
    assert s["halted"] is False


def test_sustained_real_drawdown_still_halts():
    """The glitch filter must not disable genuine risk control."""
    s = ks.update(1000.0)
    for _ in range(ks._confirmations()):
        s = ks.update(750.0, s)  # -25%, sustained
    assert s["halted"] is True


# ── Recovery ─────────────────────────────────────────────────────────────────


def test_halt_clears_once_drawdown_recovers():
    """A circuit breaker re-arms; a fuse needs replacing. This is a breaker."""
    s = ks.update(1000.0)
    for _ in range(ks._confirmations()):
        s = ks.update(800.0, s)
    assert s["halted"] is True

    s = ks.update(950.0, s)  # -5% from peak, under the re-arm threshold
    assert s["halted"] is False
    assert s["halt_reason"] is None
    assert s["halt_count"] == 1


def test_halt_persists_while_drawdown_is_still_deep():
    s = ks.update(1000.0)
    for _ in range(ks._confirmations()):
        s = ks.update(800.0, s)
    s = ks.update(830.0, s)  # -17%, still above the re-arm threshold
    assert s["halted"] is True


def test_recovery_requires_more_than_a_sliver_of_rebound():
    """Re-arm at half the max DD, not the instant it ticks back under 20%."""
    s = ks.update(1000.0)
    for _ in range(ks._confirmations()):
        s = ks.update(800.0, s)
    s = ks.update(805.0, s)  # -19.5% — under the halt line but not recovered
    assert s["halted"] is True


def test_halt_count_accumulates_across_cycles():
    s = ks.update(1000.0)
    for _ in range(2):
        for _ in range(ks._confirmations()):
            s = ks.update(800.0, s)
        s = ks.update(1000.0, s)
    assert s["halt_count"] == 2
    assert s["halted"] is False


# ── Env override ─────────────────────────────────────────────────────────────


def test_custom_max_drawdown_pct(monkeypatch):
    monkeypatch.setenv("MAX_DRAWDOWN_PCT", "0.10")
    s = ks.update(1000.0)
    s = ks.update(910.0, s)  # -9%
    assert s["halted"] is False
    for _ in range(ks._confirmations()):
        s = ks.update(900.0, s)  # -10%
    assert s["halted"] is True


def test_custom_confirmations(monkeypatch):
    monkeypatch.setenv("KILL_SWITCH_CONFIRMATIONS", "1")
    s = ks.update(1000.0)
    s = ks.update(800.0, s)
    assert s["halted"] is True


def test_custom_recovery_fraction(monkeypatch):
    monkeypatch.setenv("KILL_SWITCH_RECOVERY_FRACTION", "0.9")
    s = ks.update(1000.0)
    for _ in range(ks._confirmations()):
        s = ks.update(800.0, s)
    s = ks.update(830.0, s)  # -17% < 0.9 × 20% = 18%
    assert s["halted"] is False


# ── Backwards compatibility ──────────────────────────────────────────────────


def test_load_backfills_new_fields_on_a_legacy_state_file():
    """Files written before the confirmation/recovery fields existed."""
    legacy = {
        "peak_equity": 1084.32,
        "halted": True,
        "halted_at": 607.8,
        "halted_equity": 607.8,
        "halt_reason": "drawdown=43.7% >= max=20.0%",
    }
    Path(ks.STATE_FILE).write_text(json.dumps(legacy))

    s = ks.load()
    assert s["breach_streak"] == 0
    assert s["halt_count"] == 0
    assert s["halted"] is True  # existing halt is preserved, not silently dropped


def test_legacy_halt_clears_on_the_next_healthy_read():
    """The stuck live state must self-heal once real equity is observed."""
    legacy = {
        "peak_equity": 1084.32, "halted": True, "halted_at": 607.8,
        "halted_equity": 607.8, "halt_reason": "drawdown=43.7% >= max=20.0%",
    }
    Path(ks.STATE_FILE).write_text(json.dumps(legacy))

    s = ks.update(1081.13, ks.load())
    assert s["halted"] is False


# ── Persistence ──────────────────────────────────────────────────────────────


def test_save_and_load_round_trip(tmp_path, monkeypatch):
    s = ks.update(1000.0)
    for _ in range(ks._confirmations()):
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
    for _ in range(ks._confirmations()):
        s = ks.update(800.0, s)
    ks.save(s)
    assert ks.is_halted() is True
    assert ks.reason() is not None
