from shared import alpaca_client
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.requests import StockLatestTradeRequest


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
