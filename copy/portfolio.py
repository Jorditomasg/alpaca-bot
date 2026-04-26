"""
Manages $100 total capital across N active positions.
Each position gets an equal notional slice.
Rebalances existing positions when a new one is added or one closes.
"""
from shared import alpaca_client
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest, ClosePositionRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus


def execute_new_trade(trade: dict, state: dict) -> None:
    ticker  = trade["ticker"]
    txn     = trade["type"]  # "buy" | "sell"
    capital = state["total_capital"]
    positions = state["positions"]

    client = alpaca_client.trading()

    if txn == "buy" and ticker not in positions:
        # Add position → rebalance
        positions[ticker] = {"notional": 0.0}
        n = len(positions)
        alloc = round(capital / n, 2)

        for sym, pos in positions.items():
            old_notional = pos["notional"]
            delta = alloc - old_notional
            if abs(delta) < 1.0:
                continue
            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            try:
                client.submit_order(MarketOrderRequest(
                    symbol=sym,
                    notional=round(abs(delta), 2),
                    side=side,
                    time_in_force=TimeInForce.DAY,
                ))
                print(f"[PORTFOLIO] {side.value.upper()} ${abs(delta):.2f} {sym}")
            except Exception as e:
                print(f"[PORTFOLIO] Order failed {sym}: {e}")
            pos["notional"] = alloc

        state["positions"] = positions

    elif txn == "sell" and ticker in positions:
        # Close position → rebalance remaining
        try:
            client.close_position(ticker)
            print(f"[PORTFOLIO] Closed position {ticker}")
        except Exception as e:
            print(f"[PORTFOLIO] Close failed {ticker}: {e}")

        del positions[ticker]
        n = len(positions)
        if n == 0:
            state["positions"] = {}
            return

        alloc = round(capital / n, 2)
        for sym, pos in positions.items():
            old_notional = pos["notional"]
            delta = alloc - old_notional
            if abs(delta) < 1.0:
                continue
            try:
                client.submit_order(MarketOrderRequest(
                    symbol=sym,
                    notional=round(abs(delta), 2),
                    side=OrderSide.BUY if delta > 0 else OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                ))
            except Exception as e:
                print(f"[PORTFOLIO] Rebalance failed {sym}: {e}")
            pos["notional"] = alloc

        state["positions"] = positions
