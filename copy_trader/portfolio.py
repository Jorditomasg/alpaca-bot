"""
Manages capital across N active positions with equal notional allocation.
Processes trades in batch to avoid wash-trade cascades.
"""
from shared import alpaca_client
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus


def execute_batch(new_trades: list[dict], state: dict) -> None:
    """Process all new trades at once: update positions then rebalance once."""
    positions = state["positions"]
    capital = _get_buying_power()
    state["total_capital"] = capital
    changed = False

    for trade in new_trades:
        ticker = trade["ticker"]
        txn = trade["type"]

        if txn == "buy" and ticker not in positions:
            positions[ticker] = {"notional": 0.0}
            changed = True
        elif txn == "sell" and ticker in positions:
            del positions[ticker]
            changed = True

    if not changed:
        return

    state["positions"] = positions
    if capital > 0:
        _rebalance(positions, capital)


def _rebalance(positions: dict, capital: float) -> None:
    n = len(positions)
    if n == 0:
        return

    alloc = round(capital / n, 2)
    client = alpaca_client.trading()

    for sym, pos in positions.items():
        delta = alloc - pos["notional"]
        if abs(delta) < 1.0:
            continue

        side = OrderSide.BUY if delta > 0 else OrderSide.SELL

        # Cancel any pending orders for this symbol to avoid wash trades
        _cancel_pending(client, sym)

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


def _get_buying_power() -> float:
    try:
        client = alpaca_client.trading()
        acct = client.get_account()
        bp = float(acct.buying_power)
        print(f"[PORTFOLIO] Buying power: ${bp:,.2f}")
        return bp
    except Exception as e:
        print(f"[PORTFOLIO] Could not fetch buying power: {e} — using last known capital")
        return 0.0


def _cancel_pending(client, symbol: str) -> None:
    try:
        open_orders = client.get_orders(GetOrdersRequest(
            status=QueryOrderStatus.OPEN,
            symbols=[symbol],
        ))
        for order in open_orders:
            client.cancel_order_by_id(order.id)
            print(f"[PORTFOLIO] Cancelled pending order {order.id} for {symbol}")
    except Exception:
        pass


def close_position(ticker: str, state: dict) -> None:
    client = alpaca_client.trading()
    try:
        _cancel_pending(client, ticker)
        client.close_position(ticker)
        print(f"[PORTFOLIO] Closed position {ticker}")
    except Exception as e:
        print(f"[PORTFOLIO] Close failed {ticker}: {e}")
