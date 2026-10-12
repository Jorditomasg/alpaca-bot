"""
Executes copied trades with a fixed notional per new position — the same
sizing model the backtest harness validated (backtest/strategy.py funds each
politician buy with a fixed notional from cash and never resizes existing
positions). Sells close the full position.

The previous implementation rebalanced every position to buying_power/n on
each batch. Buying power already excludes invested capital, so each new
signal shrank the allocation target and sold slices of every existing
position — the portfolio contracted toward zero invested. Equity-based fixed
notional removes that feedback loop.

Position metadata is stamped at open time so the exits module can evaluate
stop/trailing/max-holding rules without an extra broker round-trip:
    positions[ticker] = {
        "notional": <dollars bought at open>,
        "entry_date": "YYYY-MM-DD" (UTC),
        "cost_basis": <fill price at open>,
        "high_watermark": <max close seen since entry>,
    }
"""
from datetime import datetime, timezone

from shared import alpaca_client
from shared import trader as shared_trader
import copy_trader.config as config
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus


def execute_batch(new_trades: list[dict], state: dict, *,
                  halted: bool = False) -> list[dict]:
    """Process new trades; return the subset that was actually handled.

    Buys open a position sized at NOTIONAL_PCT % of account equity, subject to
    two concentration controls (both validated in the 2018-2020 sweep):
      - MAX_POSITIONS    : never hold more than N names at once
      - MAX_INVESTED_PCT : never deploy more than this % of equity (dry powder)
    Sells close the held position (and count as handled even when nothing is
    held — there is nothing left to retry), and are NEVER blocked by the caps.

    `halted` is the account-level kill switch (shared/kill_switch.py). It stops
    new risk only: buys are skipped, sells still go through. Exits are never
    gated, per the fail-open bias documented in CLAUDE.md §7 — a halt should
    leave risk managed, not frozen.

    A buy that cannot execute right now (no equity figure, insufficient buying
    power, a cap reached, a halt, no price, order rejected) is NOT handled, so
    the caller must not mark it seen — it gets retried while the filing is
    still fresh.
    """
    positions = state["positions"]
    handled: list[dict] = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    notional = _entry_notional(state)
    equity = state.get("total_capital", 0.0)
    bp = _buying_power()
    # Deployment room left under the equity ceiling. invested ≈ equity - cash,
    # and buying power is the cash proxy (exact on a cash account).
    deploy_room = None
    if equity and equity > 0 and bp is not None:
        invested = max(0.0, equity - bp)
        deploy_room = equity * config.MAX_INVESTED_PCT / 100.0 - invested

    for trade in new_trades:
        ticker = trade["ticker"]
        txn = trade["type"]

        if txn == "buy":
            if ticker in positions:
                handled.append(trade)  # already open — nothing to do
                continue
            if halted:
                print(f"[PORTFOLIO] Skipping {ticker} — kill switch halted")
                continue
            if notional is None:
                continue  # equity unknown this cycle — retry later
            if len(positions) >= config.MAX_POSITIONS:
                print(f"[PORTFOLIO] Skipping {ticker} — at position cap "
                      f"({config.MAX_POSITIONS})")
                continue
            if deploy_room is not None and notional > deploy_room:
                print(f"[PORTFOLIO] Skipping {ticker} — deployment ceiling "
                      f"{config.MAX_INVESTED_PCT:.0f}% reached "
                      f"(room ${deploy_room:,.2f} < notional ${notional:,.2f})")
                continue
            if bp is None or bp < notional:
                print(f"[PORTFOLIO] Skipping {ticker} — buying power "
                      f"${bp if bp is not None else 0.0:,.2f} < notional ${notional:,.2f}")
                continue
            fill_price = _safe_latest_price(ticker)
            if fill_price is None:
                print(f"[PORTFOLIO] Skipping {ticker} — no entry price available")
                continue
            try:
                shared_trader.buy(ticker, notional=notional)
            except Exception as e:
                print(f"[PORTFOLIO] Buy failed {ticker}: {e}")
                continue
            _stamp_open(positions, ticker, today=today, fill_price=fill_price,
                        notional=notional)
            # Account for this fill so later buys in the same batch respect both
            # the cash balance and the deployment ceiling.
            bp -= notional
            if deploy_room is not None:
                deploy_room -= notional
            handled.append(trade)
        elif txn == "sell":
            if ticker in positions:
                if not close_position(ticker, state):
                    continue  # still held at the broker — retry next cycle
                positions.pop(ticker, None)
            handled.append(trade)

    return handled


def _entry_notional(state: dict) -> float | None:
    """Dollar size for a new position: NOTIONAL_PCT % of account equity.

    Falls back to the last known equity on API failure; returns None when no
    usable figure exists (callers skip buys and retry next cycle).
    """
    try:
        equity = shared_trader.get_equity()
        state["total_capital"] = equity
    except Exception as e:
        equity = state.get("total_capital", 0.0)
        print(f"[PORTFOLIO] Could not fetch equity: {e} — "
              f"using last known ${equity:,.2f}")
    if not equity or equity <= 0:
        return None
    notional = round(equity * config.NOTIONAL_PCT / 100.0, 2)
    # Alpaca rejects notional orders under $1.
    return notional if notional >= 1.0 else None


def _buying_power() -> float | None:
    try:
        client = alpaca_client.trading()
        return float(client.get_account().buying_power)
    except Exception as e:
        print(f"[PORTFOLIO] Could not fetch buying power: {e}")
        return None


def _stamp_open(positions: dict, ticker: str, today: str, fill_price: float,
                notional: float = 0.0) -> None:
    """Add a new position with full metadata. No-op if the ticker is already open."""
    if ticker in positions:
        return
    positions[ticker] = {
        "notional": notional,
        "entry_date": today,
        "cost_basis": fill_price,
        "high_watermark": fill_price,
    }


def close_and_remove(ticker: str, state: dict) -> None:
    """Close `ticker` at the broker and drop it from local state."""
    positions = state.get("positions", {})
    if ticker not in positions:
        return
    if close_position(ticker, state):
        positions.pop(ticker, None)


def _safe_latest_price(ticker: str) -> float | None:
    try:
        return shared_trader.get_latest_price(ticker)
    except Exception as e:
        print(f"[PORTFOLIO] get_latest_price({ticker}) failed: {e}")
        return None


def _cancel_pending(client, symbol: str) -> None:
    try:
        open_orders = client.get_orders(GetOrdersRequest(
            status=QueryOrderStatus.OPEN,
            symbols=[symbol],
        ))
        for order in open_orders:
            # The `symbols` filter is not exact: Alpaca also returns multi-leg
            # option orders (symbol=None), e.g. the wheel's spread profit-take.
            # All strategies share one account — only cancel our own ticker.
            if getattr(order, "symbol", None) != symbol:
                continue
            client.cancel_order_by_id(order.id)
            print(f"[PORTFOLIO] Cancelled pending order {order.id} for {symbol}")
    except Exception:
        pass


def close_position(ticker: str, state: dict) -> bool:
    """Close `ticker` at the broker. True when nothing is left to close.

    False means the close failed and the shares are still held: callers must
    keep the position in local state so the exit is retried, instead of
    dropping it and leaving an unwatched position at the broker.
    """
    client = alpaca_client.trading()
    try:
        _cancel_pending(client, ticker)
        client.close_position(ticker)
        print(f"[PORTFOLIO] Closed position {ticker}")
        return True
    except Exception as e:
        if "40410000" in str(e) or "position does not exist" in str(e).lower():
            print(f"[PORTFOLIO] {ticker} already flat at the broker — dropping it")
            return True
        print(f"[PORTFOLIO] Close failed {ticker}: {e}")
        return False
