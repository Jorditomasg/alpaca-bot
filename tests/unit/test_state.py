"""Unit tests for wheel/state.py — schema, migration, round-trip IO."""
import json
import pytest
from pathlib import Path
import wheel.state as state_mod


# ── helpers ──────────────────────────────────────────────────────────────────

def _write_state(tmp_path: Path, data: dict) -> Path:
    f = tmp_path / "wheel_state.json"
    f.write_text(json.dumps(data))
    return f


# ── legacy-file migration ────────────────────────────────────────────────────

def test_legacy_csp_file_gets_strategy_type_csp(tmp_path, monkeypatch, capsys):
    """Old state files without strategy_type must load with strategy_type='csp'."""
    legacy = {
        "stage": "IDLE",
        "symbol": "TSLA",
        "contract_symbol": None,
        "contract_strike": None,
        "contract_expiry": None,
        "premium_received": 0.0,
        "total_premium": 0.0,
        "cost_basis": None,
        "shares_owned": 0,
        "cycles": 3,
    }
    state_file = _write_state(tmp_path, legacy)
    monkeypatch.setattr(state_mod, "STATE_FILE", state_file)

    s = state_mod.load()
    assert s["strategy_type"] == "csp"

    # Migration banner must be printed exactly once
    captured = capsys.readouterr()
    assert "Legacy state detected" in captured.out


def test_legacy_file_gets_spread_fields_as_none(tmp_path, monkeypatch):
    """Spread fields are backfilled with None/0 when absent."""
    legacy = {
        "stage": "IDLE",
        "symbol": "TSLA",
        "contract_symbol": None,
        "contract_strike": None,
        "contract_expiry": None,
        "premium_received": 0.0,
        "total_premium": 0.0,
        "cost_basis": None,
        "shares_owned": 0,
        "cycles": 0,
    }
    state_file = _write_state(tmp_path, legacy)
    monkeypatch.setattr(state_mod, "STATE_FILE", state_file)

    s = state_mod.load()
    assert s["short_symbol"] is None
    assert s["long_symbol"] is None
    assert s["short_strike"] is None
    assert s["long_strike"] is None
    assert s["net_credit"] == 0.0
    assert s["max_loss"] == 0.0
    assert s["last_logged_insufficient_at"] is None


# ── fresh state ──────────────────────────────────────────────────────────────

def test_fresh_state_uses_config_strategy(tmp_path, monkeypatch):
    """When no state file exists, strategy_type comes from WheelConfig."""
    monkeypatch.setenv("WHEEL_STRATEGY_TYPE", "bull_put_spread")
    monkeypatch.setenv("WHEEL_SYMBOL", "SOFI")
    missing = tmp_path / "wheel_state.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", missing)

    s = state_mod.load()
    assert s["strategy_type"] == "bull_put_spread"
    assert s["symbol"] == "SOFI"


def test_fresh_state_stage_is_idle(tmp_path, monkeypatch):
    missing = tmp_path / "wheel_state.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", missing)
    s = state_mod.load()
    assert s["stage"] == "IDLE"


def test_fresh_state_spread_fields_are_null(tmp_path, monkeypatch):
    missing = tmp_path / "wheel_state.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", missing)

    s = state_mod.load()
    for field in ("short_symbol", "short_strike", "long_symbol", "long_strike",
                  "contract_symbol", "cost_basis"):
        assert s[field] is None, f"expected {field} to be None, got {s[field]}"


# ── round-trip JSON ──────────────────────────────────────────────────────────

def test_save_and_load_round_trip(tmp_path, monkeypatch):
    state_file = tmp_path / "wheel_state.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", state_file)
    # Use missing file path to get fresh state
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", missing)
    s = state_mod.load()

    # Simulate SPREAD_OPEN data
    s["stage"] = "SPREAD_OPEN"
    s["short_symbol"] = "SOFI260117P00009000"
    s["short_strike"] = 9.0
    s["long_symbol"] = "SOFI260117P00007000"
    s["long_strike"] = 7.0
    s["net_credit"] = 62.0
    s["max_loss"] = 138.0
    s["contract_expiry"] = "2026-01-17"

    # Now save and re-load from real file
    monkeypatch.setattr(state_mod, "STATE_FILE", state_file)
    state_mod.save(s)
    loaded = state_mod.load()

    assert loaded["stage"] == "SPREAD_OPEN"
    assert loaded["short_symbol"] == "SOFI260117P00009000"
    assert loaded["net_credit"] == 62.0
    assert loaded["strategy_type"] == "bull_put_spread"


def test_no_tsla_hardcode_in_fresh_state(tmp_path, monkeypatch):
    """Fresh state must never contain TSLA when WHEEL_SYMBOL is set."""
    monkeypatch.setenv("WHEEL_SYMBOL", "SOFI")
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", missing)
    s = state_mod.load()
    # symbol from config, not hardcoded
    assert s["symbol"] == "SOFI"
    assert "TSLA" not in str(s)


# ── Symbol migration override (Fix #4) ──────────────────────────────────────

def test_legacy_idle_symbol_overridden_by_env(tmp_path, monkeypatch, capsys):
    """Legacy IDLE state + WHEEL_SYMBOL env → symbol updated in memory."""
    legacy = {
        "stage": "IDLE",
        "symbol": "TSLA",
        "strategy_type": "bull_put_spread",
        "contract_symbol": None,
        "contract_strike": None,
        "contract_expiry": None,
        "premium_received": 0.0,
        "total_premium": 0.0,
        "cost_basis": None,
        "shares_owned": 0,
        "cycles": 0,
    }
    state_file = _write_state(tmp_path, legacy)
    monkeypatch.setattr(state_mod, "STATE_FILE", state_file)
    monkeypatch.setenv("WHEEL_SYMBOL", "SOFI")

    s = state_mod.load()
    assert s["symbol"] == "SOFI"
    out = capsys.readouterr().out
    assert "Symbol overridden" in out or "overridden" in out.lower()


def test_legacy_put_open_preserves_symbol_with_warning(tmp_path, monkeypatch, capsys):
    """Legacy PUT_OPEN state + WHEEL_SYMBOL env → symbol preserved, warning logged."""
    legacy = {
        "stage": "PUT_OPEN",
        "symbol": "TSLA",
        "strategy_type": "csp",
        "contract_symbol": "TSLA260117P00090000",
        "contract_strike": 90.0,
        "contract_expiry": "2026-01-17",
        "premium_received": 60.0,
        "total_premium": 60.0,
        "cost_basis": None,
        "shares_owned": 0,
        "cycles": 0,
    }
    state_file = _write_state(tmp_path, legacy)
    monkeypatch.setattr(state_mod, "STATE_FILE", state_file)
    monkeypatch.setenv("WHEEL_SYMBOL", "SOFI")

    s = state_mod.load()
    # Symbol must be preserved — in-flight position should not be orphaned
    assert s["symbol"] == "TSLA"
    out = capsys.readouterr().out
    # Warning must be logged about the mismatch
    assert "WARNING" in out or "wait until IDLE" in out


def test_no_env_symbol_preserves_existing(tmp_path, monkeypatch):
    """When WHEEL_SYMBOL is absent from env, existing symbol is preserved."""
    legacy = {
        "stage": "IDLE",
        "symbol": "TSLA",
        "strategy_type": "csp",
        "contract_symbol": None,
        "contract_strike": None,
        "contract_expiry": None,
        "premium_received": 0.0,
        "total_premium": 0.0,
        "cost_basis": None,
        "shares_owned": 0,
        "cycles": 0,
    }
    state_file = _write_state(tmp_path, legacy)
    monkeypatch.setattr(state_mod, "STATE_FILE", state_file)
    monkeypatch.delenv("WHEEL_SYMBOL", raising=False)

    s = state_mod.load()
    # No env var set → symbol preserved as-is
    assert s["symbol"] == "TSLA"


# ── Atomic save (Fix #5) ──────────────────────────────────────────────────────

def test_save_creates_valid_json(tmp_path, monkeypatch):
    """save() writes a readable, valid JSON file."""
    state_file = tmp_path / "wheel_state.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", state_file)

    missing = tmp_path / "missing.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", missing)
    s = state_mod.load()

    monkeypatch.setattr(state_mod, "STATE_FILE", state_file)
    state_mod.save(s)

    assert state_file.exists()
    loaded = json.loads(state_file.read_text())
    assert loaded["stage"] == "IDLE"


def test_save_leaves_no_tmp_file_leak(tmp_path, monkeypatch):
    """After a successful save, no .tmp file should remain in the directory."""
    state_file = tmp_path / "wheel_state.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", state_file)

    missing = tmp_path / "missing.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", missing)
    s = state_mod.load()

    monkeypatch.setattr(state_mod, "STATE_FILE", state_file)
    state_mod.save(s)

    tmp_files = list(tmp_path.glob(".wheel_state_*.tmp"))
    assert tmp_files == [], f"Leaked temp files: {tmp_files}"
