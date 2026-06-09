"""Shared test fixtures for alpaca-bot test suite."""
import json
import pathlib
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def load_chain_fixture():
    """Load an option-chain fixture, re-basing expiries to preserve DTE.

    Fixtures store absolute expiration dates captured on `captured_at`; the
    suite runs arbitrarily later. Shifting every expiration_date by
    (today - captured_at) keeps each contract's days-to-expiry identical to
    capture day, so DTE-window logic behaves the same forever.
    """
    def _load(name: str) -> dict:
        chain = json.loads((FIXTURES / "option_chains" / name).read_text())
        captured = chain.get("captured_at")
        if captured:
            captured_day = datetime.fromisoformat(
                str(captured).replace("Z", "+00:00")
            ).date()
            shift = (date.today() - captured_day).days
            if shift > 0:
                for c in chain.get("contracts", []):
                    exp = date.fromisoformat(c["expiration_date"])
                    c["expiration_date"] = str(exp + timedelta(days=shift))
        return chain
    return _load


@pytest.fixture
def mock_trading_client(mocker):
    client = MagicMock()
    mocker.patch("shared.alpaca_client.trading", return_value=client)
    return client


@pytest.fixture
def mock_option_data_client(mocker):
    client = MagicMock()
    mocker.patch("shared.alpaca_client.option_data", return_value=client)
    return client


@pytest.fixture(autouse=True)
def _isolate_kill_switch_state(monkeypatch, tmp_path):
    """Tests must never read or write the LIVE data/kill_switch.json.

    The module resolves its state file relative to cwd; running the suite from
    the deployment checkout would otherwise hit the bot's real (root-owned)
    state — failing on permissions at best, corrupting risk state at worst.
    """
    import shared.kill_switch as ks
    monkeypatch.setattr(ks, "STATE_FILE", tmp_path / "kill_switch.json")


@pytest.fixture(autouse=True)
def _reset_wheel_config_cache():
    from wheel.config import get_config
    get_config.cache_clear()
    yield
    get_config.cache_clear()


@pytest.fixture
def wheel_env(monkeypatch):
    """Helper to set a coherent wheel env in one call."""
    def _set(**kwargs):
        defaults = {
            "WHEEL_STRATEGY_TYPE": "bull_put_spread",
            "WHEEL_SYMBOL": "SOFI",
            "WHEEL_SPREAD_WIDTH": "2",
        }
        defaults.update({k.upper(): str(v) for k, v in kwargs.items()})
        for k, v in defaults.items():
            monkeypatch.setenv(k, v)
    return _set
