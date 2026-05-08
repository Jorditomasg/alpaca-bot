"""Shared test fixtures for alpaca-bot test suite."""
import json
import pathlib
import pytest
from unittest.mock import MagicMock

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def load_chain_fixture():
    def _load(name: str) -> dict:
        return json.loads((FIXTURES / "option_chains" / name).read_text())
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
