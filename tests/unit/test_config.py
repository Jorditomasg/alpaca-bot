"""Unit tests for wheel/config.py."""
import pytest
from wheel.config import get_config


def test_default_strategy_type():
    cfg = get_config()
    assert cfg.strategy_type == "bull_put_spread"


def test_default_symbol():
    cfg = get_config()
    assert cfg.symbol == "SOFI"


def test_default_spread_width():
    cfg = get_config()
    assert cfg.spread_width == 2.0


def test_default_min_buying_power():
    cfg = get_config()
    # default = width * 100 * 2 = 2 * 100 * 2 = 400
    assert cfg.min_buying_power == 400.0


def test_default_dte_range():
    cfg = get_config()
    assert cfg.target_dte_min == 14
    assert cfg.target_dte_max == 28


def test_default_profit_target():
    cfg = get_config()
    assert cfg.profit_target_pct == 50.0


def test_default_otm_pct():
    cfg = get_config()
    assert cfg.target_otm_pct == 0.10


def test_default_score_threshold():
    cfg = get_config()
    assert cfg.score_threshold == 0.30


def test_env_override_strategy_type(monkeypatch):
    monkeypatch.setenv("WHEEL_STRATEGY_TYPE", "csp")
    cfg = get_config()
    assert cfg.strategy_type == "csp"


def test_env_override_symbol(monkeypatch):
    monkeypatch.setenv("WHEEL_SYMBOL", "AAPL")
    cfg = get_config()
    assert cfg.symbol == "AAPL"


def test_env_override_spread_width(monkeypatch):
    monkeypatch.setenv("WHEEL_SPREAD_WIDTH", "5")
    cfg = get_config()
    assert cfg.spread_width == 5.0


def test_env_override_min_buying_power(monkeypatch):
    monkeypatch.setenv("WHEEL_MIN_BUYING_POWER", "1000")
    cfg = get_config()
    assert cfg.min_buying_power == 1000.0


def test_env_override_dte_min(monkeypatch):
    monkeypatch.setenv("WHEEL_TARGET_DTE_MIN", "7")
    cfg = get_config()
    assert cfg.target_dte_min == 7


def test_env_override_dte_max(monkeypatch):
    monkeypatch.setenv("WHEEL_TARGET_DTE_MAX", "45")
    cfg = get_config()
    assert cfg.target_dte_max == 45


def test_env_override_profit_target(monkeypatch):
    monkeypatch.setenv("WHEEL_PROFIT_TARGET_PCT", "25")
    cfg = get_config()
    assert cfg.profit_target_pct == 25.0


def test_env_override_otm_pct(monkeypatch):
    monkeypatch.setenv("WHEEL_TARGET_OTM_PCT", "0.05")
    cfg = get_config()
    assert cfg.target_otm_pct == 0.05


def test_min_bp_derived_from_width_when_not_set(monkeypatch):
    monkeypatch.setenv("WHEEL_SPREAD_WIDTH", "3")
    # WHEEL_MIN_BUYING_POWER is NOT set — should derive as 3*100*2=600
    cfg = get_config()
    assert cfg.min_buying_power == 600.0


def test_config_is_frozen():
    cfg = get_config()
    with pytest.raises((AttributeError, TypeError)):
        cfg.symbol = "TSLA"  # type: ignore[misc]


def test_cache_clear_allows_re_read(monkeypatch):
    cfg1 = get_config()
    assert cfg1.symbol == "SOFI"
    get_config.cache_clear()
    monkeypatch.setenv("WHEEL_SYMBOL", "NVDA")
    cfg2 = get_config()
    assert cfg2.symbol == "NVDA"
