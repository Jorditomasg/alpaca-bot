import os
from functools import lru_cache
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.option import OptionHistoricalDataClient


def _key() -> str:    return os.environ["ALPACA_API_KEY"]
def _secret() -> str: return os.environ["ALPACA_SECRET_KEY"]


def trading() -> TradingClient:
    return TradingClient(_key(), _secret(), paper=True)


def stock_data() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(_key(), _secret())


def option_data() -> OptionHistoricalDataClient:
    return OptionHistoricalDataClient(_key(), _secret())
