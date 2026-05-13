"""
Manages capital across N active positions with equal notional allocation.
Processes trades in batch to avoid wash-trade cascades.

Position metadata is stamped at open time so the exits module can evaluate
stop/trailing/max-holding rules without an extra broker round-trip:
    positions[ticker] = {
        "notional": <set by _rebalance>,
        "entry_date": "YYYY-MM-DD" (UTC),
        "cost_basis": <fill price at open>,
        "high_watermark": <max close seen since entry>,
    }
"""
from datetime import datetime, timezone

from shared import alpaca_client
from shared import trader as shared_trader
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus


def execute_batch(new_trades: list[dict], state: dict) -> None:
    """Process all new trades at once: update positions then rebalance once."""
    positions = state["positions"]
    capital = _get_buying_power(state)
    state["total_capital"] = capital
    changed = False
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for trade in new_trades:
        ticker = trade["ticker"]
        txn = trade["type"]

        if txn == "buy" and ticker not in positions:
            fill_price = _safe_latest_price(ticker)
            if fill_price is None:
                print(f"[PORTFOLIO] Skipping {ticker} — no entry price available")
                continue
            _stamp_open(positions, ticker, today=today, fill_price=fill_price)
            changed = True
        elif txn == "sell" and ticker in positions:
            close_position(ticker, state)
            del positions[ticker]
            changed = True

    if not changed:
        return

    state["positions"] = positions
    if capital > 0:
        _rebalance(positions, capital)


def _stamp_open(positions: dict, ticker: str, today: str, fill_price: float) -> None:
    """Add a new position with full metadata. No-op if the ticker is already open."""
    if ticker in positions:
        return
    positions[ticker] = {
        "notional": 0.0,
        "entry_date": today,
        "cost_basis": fill_price,
        "high_watermark": fill_price,
    }


def close_and_remove(ticker: str, state: dict) -> None:
    """Close `ticker` at the broker and drop it from local state."""
    positions = state.get("positions", {})
    if ticker not in positions:
        return
    close_position(ticker, state)
    positions.pop(ticker, None)


def _safe_latest_price(ticker: str) -> float | None:
    try:
        return shared_trader.get_latest_price(ticker)
    except Exception as e:
        print(f"[PORTFOLIO] get_latest_price({ticker}) failed: {e}")
        return None


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
            pos["notional"] = alloc
            print(f"[PORTFOLIO] {side.value.upper()} ${abs(delta):.2f} {sym}")
        except Exception as e:
            print(f"[PORTFOLIO] Order failed {sym}: {e}")


def _get_buying_power(state: dict) -> float:
    try:
        client = alpaca_client.trading()
        acct = client.get_account()
        bp = float(acct.buying_power)
        print(f"[PORTFOLIO] Buying power: ${bp:,.2f}")
        return bp
    except Exception as e:
        fallback = state.get("total_capital", 0.0)
        print(f"[PORTFOLIO] Could not fetch buying power: {e} — using last known ${fallback:,.2f}")
        return fallback


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
