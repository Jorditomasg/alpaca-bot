from datetime import datetime, timedelta, timezone

from shared import alpaca_client
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.requests import StockLatestTradeRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame


def buy(symbol: str, qty: float = None, notional: float = None):
    client = alpaca_client.trading()
    request_params = {
        "symbol": symbol,
        "side": OrderSide.BUY,
        "time_in_force": TimeInForce.DAY,
    }
    if notional is not None:
        request_params["notional"] = round(notional, 2)
    elif qty is not None:
        request_params["qty"] = qty
    else:
        raise ValueError("Either qty or notional must be provided")

    order = client.submit_order(MarketOrderRequest(**request_params))
    
    amount_str = f"${notional:.2f}" if notional else f"{qty} shares"
    print(f"[TRADER] BUY  {amount_str:>8} {symbol} | id={order.id} | status={order.status}")
    return order


def sell(symbol: str, qty: float = None, notional: float = None):
    client = alpaca_client.trading()
    request_params = {
        "symbol": symbol,
        "side": OrderSide.SELL,
        "time_in_force": TimeInForce.DAY,
    }
    if notional is not None:
        request_params["notional"] = round(notional, 2)
    elif qty is not None:
        request_params["qty"] = qty
    else:
        raise ValueError("Either qty or notional must be provided")

    order = client.submit_order(MarketOrderRequest(**request_params))
    
    amount_str = f"${notional:.2f}" if notional else f"{qty} shares"
    print(f"[TRADER] SELL {amount_str:>8} {symbol} | id={order.id} | status={order.status}")
    return order


def get_latest_price(symbol: str) -> float:
    client = alpaca_client.stock_data()
    trade = client.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=symbol))
    return float(trade[symbol].price)


def get_buying_power() -> float:
    client = alpaca_client.trading()
    account = client.get_account()
    return float(account.buying_power)


def get_equity() -> float:
    """Account total equity (cash + positions market value)."""
    client = alpaca_client.trading()
    account = client.get_account()
    return float(account.equity)


def get_recent_bars(symbol: str, days: int = 30) -> list[dict]:
    """Fetch the last `days` daily OHLC bars for a symbol.

    Returns a list of dicts oldest-first with keys: open, high, low, close, volume.
    Empty list on data-API failure (caller decides fallback).

    Note: Alpaca's free-tier IEX feed has a 15-minute delay on equity data,
    but daily bars from the previous session are fine for ATR.
    """
    try:
        client = alpaca_client.stock_data()
        # Add a buffer for weekends/holidays — we want `days` *trading* sessions.
        start = datetime.now(timezone.utc) - timedelta(days=days * 2)
        resp = client.get_stock_bars(StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=start,
        ))
        # alpaca-py returns a BarSet keyed by symbol → list[Bar]
        bars = resp.data.get(symbol, [])
        out = [
            {
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": float(b.volume),
            }
            for b in bars
        ]
        # Trim to the most recent `days` bars.
        return out[-days:] if len(out) > days else out
    except Exception as e:
        print(f"[TRADER] get_recent_bars({symbol}) failed: {e}")
        return []
