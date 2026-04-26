"""
Wheel strategy state machine.

IDLE        → PUT_OPEN   : sell cash-secured put
PUT_OPEN    → ASSIGNED   : put assigned (stock position detected)
PUT_OPEN    → PUT_OPEN   : put expired worthless → sell new put
ASSIGNED    → CALL_OPEN  : sell covered call
CALL_OPEN   → IDLE       : call exercised (shares gone) → restart
CALL_OPEN   → CALL_OPEN  : call expired worthless → sell new call
"""
import alpaca_client
import wheel.options as options_mod
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType
from alpaca.data.requests import StockLatestTradeRequest


def run_cycle(state: dict) -> dict:
    stage = state["stage"]
    symbol = state["symbol"]

    if stage == "IDLE":
        return _open_put(state, symbol)
    elif stage == "PUT_OPEN":
        return _check_put(state, symbol)
    elif stage == "ASSIGNED":
        return _open_call(state, symbol)
    elif stage == "CALL_OPEN":
        return _check_call(state, symbol)

    return state


# ── IDLE → PUT_OPEN ────────────────────────────────────────────────────────

def _open_put(state: dict, symbol: str) -> dict:
    price = _get_stock_price(symbol)
    if not price:
        return state

    contract = options_mod.best_put(symbol, price)
    if not contract:
        print(f"[WHEEL] No suitable put found for {symbol}")
        return state

    # Cash-secured put check: need strike × 100 in buying power
    client = alpaca_client.trading()
    acct = client.get_account()
    required_cash = contract["strike"] * 100
    if float(acct.buying_power) < required_cash:
        print(f"[WHEEL] Insufficient buying power ${acct.buying_power} < ${required_cash}")
        return state

    try:
        order = client.submit_order(LimitOrderRequest(
            symbol=contract["symbol"],
            qty=1,
            side=OrderSide.SELL,
            type=OrderType.LIMIT,
            limit_price=round(contract["premium"], 2),
            time_in_force=TimeInForce.DAY,
        ))
        premium = contract["premium"] * 100  # 1 contract = 100 shares
        state["stage"] = "PUT_OPEN"
        state["contract_symbol"] = contract["symbol"]
        state["contract_strike"] = contract["strike"]
        state["contract_expiry"] = contract["expiry"]
        state["premium_received"] = premium
        state["total_premium"] += premium
        print(f"[WHEEL] PUT sold: {contract['symbol']} | strike=${contract['strike']} "
              f"| expiry={contract['expiry']} | premium=${premium:.2f}")
    except Exception as e:
        print(f"[WHEEL] PUT order failed: {e}")

    return state


# ── PUT_OPEN checks ─────────────────────────────────────────────────────────

def _check_put(state: dict, symbol: str) -> dict:
    contract_sym = state["contract_symbol"]
    if not contract_sym:
        state["stage"] = "IDLE"
        return state

    # Check if we got assigned: look for stock position
    client = alpaca_client.trading()
    try:
        pos = client.get_open_position(symbol)
        qty = int(pos.qty)
        if qty >= 100:
            # Assigned!
            assignment_price = state["contract_strike"]
            premiums_per_share = state["total_premium"] / 100
            state["stage"] = "ASSIGNED"
            state["shares_owned"] = qty
            state["cost_basis"] = round(assignment_price - premiums_per_share, 4)
            state["contract_symbol"] = None
            print(f"[WHEEL] ASSIGNED! {qty} shares @ ${assignment_price} | "
                  f"cost_basis=${state['cost_basis']:.2f}")
    except Exception:
        # No stock position → put still open or expired worthless
        pass

    # Check if put expired (no open option position)
    if state["stage"] == "PUT_OPEN":
        quote = options_mod.get_quote(contract_sym)
        if quote is None or quote < 0.05:
            print(f"[WHEEL] Put expired worthless → selling new put")
            state["stage"] = "IDLE"
            state["contract_symbol"] = None
            state["cycles"] += 1
            return _open_put(state, symbol)

    return state


# ── ASSIGNED → CALL_OPEN ───────────────────────────────────────────────────

def _open_call(state: dict, symbol: str) -> dict:
    cost_basis = state["cost_basis"]
    contract = options_mod.best_call(symbol, cost_basis)
    if not contract:
        print(f"[WHEEL] No suitable call found for {symbol}")
        return state

    # Never sell call below cost basis
    if contract["strike"] < cost_basis:
        print(f"[WHEEL] Call strike ${contract['strike']} < cost_basis ${cost_basis:.2f} — skipping")
        return state

    client = alpaca_client.trading()
    try:
        client.submit_order(LimitOrderRequest(
            symbol=contract["symbol"],
            qty=1,
            side=OrderSide.SELL,
            type=OrderType.LIMIT,
            limit_price=round(contract["premium"], 2),
            time_in_force=TimeInForce.DAY,
        ))
        premium = contract["premium"] * 100
        state["stage"] = "CALL_OPEN"
        state["contract_symbol"] = contract["symbol"]
        state["contract_strike"] = contract["strike"]
        state["contract_expiry"] = contract["expiry"]
        state["premium_received"] = premium
        state["total_premium"] += premium
        print(f"[WHEEL] CALL sold: {contract['symbol']} | strike=${contract['strike']} "
              f"| expiry={contract['expiry']} | premium=${premium:.2f}")
    except Exception as e:
        print(f"[WHEEL] CALL order failed: {e}")

    return state


# ── CALL_OPEN checks ────────────────────────────────────────────────────────

def _check_call(state: dict, symbol: str) -> dict:
    contract_sym = state["contract_symbol"]
    if not contract_sym:
        state["stage"] = "ASSIGNED"
        return state

    client = alpaca_client.trading()

    # Check if shares were called away
    try:
        pos = client.get_open_position(symbol)
        qty = int(pos.qty)
    except Exception:
        qty = 0

    if qty == 0:
        print(f"[WHEEL] Shares called away → restarting cycle")
        state["stage"] = "IDLE"
        state["contract_symbol"] = None
        state["shares_owned"] = 0
        state["cost_basis"] = None
        state["cycles"] += 1
        return state

    # Check if call expired worthless
    quote = options_mod.get_quote(contract_sym)
    if quote is None or quote < 0.05:
        print(f"[WHEEL] Call expired worthless → selling new call")
        state["stage"] = "ASSIGNED"
        state["contract_symbol"] = None
        state["cycles"] += 1
        return _open_call(state, symbol)

    return state


# ── helpers ─────────────────────────────────────────────────────────────────

def _get_stock_price(symbol: str) -> float | None:
    try:
        client = alpaca_client.stock_data()
        resp = client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=symbol)
        )
        return float(resp[symbol].price)
    except Exception as e:
        print(f"[WHEEL] Price fetch failed: {e}")
        return None
