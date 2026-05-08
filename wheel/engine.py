"""
Wheel strategy state machine — dispatcher + CSP + spread engines.

Strategy dispatch:
  run_cycle(state) reads state["strategy_type"] and delegates to:
    _run_csp_cycle()    — legacy four-state CSP machine (IDLE→PUT_OPEN→ASSIGNED→CALL_OPEN)
    _run_spread_cycle() — bull-put-spread two-state machine (IDLE→SPREAD_OPEN)

CSP state transitions:
  IDLE        → PUT_OPEN   : sell cash-secured put
  PUT_OPEN    → ASSIGNED   : put assigned (stock position detected)
  PUT_OPEN    → PUT_OPEN   : put expired worthless → sell new put
  ASSIGNED    → CALL_OPEN  : sell covered call
  CALL_OPEN   → IDLE       : call exercised (shares gone) → restart
  CALL_OPEN   → CALL_OPEN  : call expired worthless → sell new call

Spread state transitions (bull_put_spread):
  IDLE        → SPREAD_OPEN : sell bull put spread (defined-risk; no assignment possible)
  SPREAD_OPEN → IDLE        : profit-take at 50% of net credit
  SPREAD_OPEN → IDLE        : expiry worthless (full credit kept)
  SPREAD_OPEN → IDLE        : max-loss at expiry (underlying < long strike)
"""
from __future__ import annotations
from datetime import date

from shared import alpaca_client
import wheel.options as options_mod
import wheel.spreads as spreads_mod
from wheel.config import get_config
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType
from alpaca.data.requests import StockLatestTradeRequest, OptionLatestQuoteRequest


# ── public entry point ────────────────────────────────────────────────────────

def run_cycle(state: dict) -> dict:
    strategy = state.get("strategy_type", "csp")
    if strategy == "bull_put_spread":
        return _run_spread_cycle(state)
    return _run_csp_cycle(state)


# ── CSP engine (bit-for-bit identical to original) ───────────────────────────

def _run_csp_cycle(state: dict) -> dict:
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


# ── Spread engine ─────────────────────────────────────────────────────────────

def _run_spread_cycle(state: dict) -> dict:
    cfg = get_config()
    stage = state["stage"]

    if stage == "IDLE":
        # Capital guard applies only when opening new positions, not when closing
        if _capital_guard(state, cfg.min_buying_power, "spread"):
            return state
        return _open_spread(state, cfg)
    elif stage == "SPREAD_OPEN":
        # No capital guard here — closing a spread releases collateral and must
        # never be blocked by an insufficient buying-power check.
        return _check_spread(state, cfg)

    return state


def _open_spread(state: dict, cfg) -> dict:
    symbol = state["symbol"]

    price = _get_stock_price(symbol)
    if price is None:
        return state

    chain = _fetch_option_chain(symbol, price, cfg)
    if chain is None:
        return state

    candidate = spreads_mod.best_bull_put_spread(symbol, price, chain, cfg)
    if candidate is None:
        print(f"[WHEEL] No qualifying spread found for {symbol} — staying IDLE")
        return state

    order = spreads_mod.build_open_order(
        candidate["short_symbol"],
        candidate["long_symbol"],
        round(candidate["net_credit"] / 100, 2),  # per-share credit
    )

    # Submit BEFORE mutating state so a rejected/failed order leaves state IDLE.
    client = alpaca_client.trading()
    try:
        client.submit_order(order)
    except Exception as e:
        print(f"[WHEEL] Spread order failed: {e}")
        return state  # state unchanged — still IDLE

    # Order accepted — commit state changes only after confirmed submission
    state["stage"] = "SPREAD_OPEN"
    state["short_symbol"] = candidate["short_symbol"]
    state["short_strike"] = candidate["short_strike"]
    state["long_symbol"] = candidate["long_symbol"]
    state["long_strike"] = candidate["long_strike"]
    state["contract_expiry"] = candidate["expiry"]
    state["net_credit"] = candidate["net_credit"]
    state["max_loss"] = candidate["max_loss"]
    state["spread_width"] = candidate["width"]
    state["premium_received"] = candidate["net_credit"]
    state["total_premium"] += candidate["net_credit"]
    print(
        f"[WHEEL] SPREAD opened: {candidate['short_symbol']}/{candidate['long_symbol']} "
        f"| credit=${candidate['net_credit']:.2f} | score={candidate['score']:.2f}"
    )
    return state


def _check_spread(state: dict, cfg) -> dict:
    short_sym = state.get("short_symbol")
    long_sym = state.get("long_symbol")
    expiry_str = state.get("contract_expiry")
    net_credit = state.get("net_credit", 0.0)

    if not short_sym or not long_sym:
        # Guard against corrupted state — reset to IDLE
        state["stage"] = "IDLE"
        return state

    # ── Expiry handling ──────────────────────────────────────────────────────
    if expiry_str:
        try:
            exp_date = date.fromisoformat(str(expiry_str))
        except ValueError:
            exp_date = None

        if exp_date and date.today() >= exp_date:
            symbol = state["symbol"]
            price = _get_stock_price(symbol)
            short_strike = state.get("short_strike", 0.0)
            long_strike = state.get("long_strike", 0.0)
            max_loss = state.get("max_loss", (state.get("spread_width", 2) * 100) - net_credit)

            if price is not None and price >= short_strike:
                # Both legs expire worthless → full credit kept
                # Credit was already booked at open via total_premium += net_credit;
                # no further adjustment needed.
                realized = net_credit
                print(
                    f"[WHEEL] SPREAD expired worthless: underlying={price:.2f} >= "
                    f"short_strike={short_strike} | realized=+${realized:.2f}"
                )
            elif price is not None and price >= long_strike:
                # Short ITM, long OTM → partial loss; clamped to [0, max_loss].
                # Credit was already booked at open; subtract only the intrinsic loss.
                intrinsic = (short_strike - price) * 100
                realized = max(-max_loss, net_credit - intrinsic)
                # Reverse the optimistic credit, apply actual realized P&L
                state["total_premium"] -= net_credit
                state["total_premium"] += realized
                print(
                    f"[WHEEL] SPREAD partial loss at expiry: underlying={price:.2f} "
                    f"between strikes | intrinsic=${intrinsic:.2f} | realized=${realized:.2f}"
                )
            else:
                # Both ITM → full max loss.
                # Credit was already booked at open; subtract net loss = max_loss - net_credit
                # plus reverse the credit so total_premium reflects true loss.
                realized = net_credit - max_loss
                state["total_premium"] -= net_credit
                state["total_premium"] += realized
                print(
                    f"[WHEEL] SPREAD max-loss at expiry: underlying={price:.2f} < "
                    f"long_strike={long_strike} | realized=${realized:.2f}"
                )

            state["realized_pnl"] = state.get("realized_pnl", 0.0) + realized
            state["cycles"] += 1
            return _reset_spread_fields(state)

    # ── Early profit-take at 50% ─────────────────────────────────────────────
    short_quote = _get_option_quote(short_sym)
    long_quote  = _get_option_quote(long_sym)

    if short_quote is not None and long_quote is not None:
        # Conservative current close cost: short_bid - long_ask
        current_cost = spreads_mod.spread_mid_price(short_quote["bid"], long_quote["ask"])
        profit_target_per_share = (net_credit / 100) * (1.0 - cfg.profit_target_pct / 100.0)

        if current_cost <= profit_target_per_share:
            close_order = spreads_mod.build_close_order(
                short_sym,
                long_sym,
                round(current_cost, 2),
            )
            client = alpaca_client.trading()
            try:
                client.submit_order(close_order)
                print(
                    f"[WHEEL] SPREAD profit-take: cost=${current_cost:.2f} ≤ "
                    f"target=${profit_target_per_share:.2f} → closing"
                )
                state["cycles"] += 1
                return _reset_spread_fields(state)
            except Exception as e:
                print(f"[WHEEL] Spread close order failed: {e}")

    return state


def _reset_spread_fields(state: dict) -> dict:
    state["stage"] = "IDLE"
    state["short_symbol"] = None
    state["short_strike"] = None
    state["long_symbol"] = None
    state["long_strike"] = None
    state["net_credit"] = 0.0
    state["max_loss"] = 0.0
    state["contract_expiry"] = None
    state["premium_received"] = 0.0
    return state


# ── Capital guard ─────────────────────────────────────────────────────────────

def _capital_guard(state: dict, required: float, label: str) -> bool:
    """Return True if the cycle should HALT due to insufficient buying power.

    Logs exactly ONE warning per (rounded_bp, cycles) bucket. A new bucket
    triggers a re-log. Recovery above threshold clears the latch.
    """
    try:
        client = alpaca_client.trading()
        bp = float(client.get_account().buying_power)
    except Exception as e:
        print(f"[WHEEL] Could not fetch buying power: {e}")
        return True  # Fail safe: halt if we can't check

    if bp >= required:
        # Recovered — clear latch so next shortfall logs immediately
        state["last_logged_insufficient_at"] = None
        return False

    # Insufficient buying power. Latch by (rounded_bp, cycles) bucket.
    bucket = (round(bp, 0), state.get("cycles", 0))
    last = state.get("last_logged_insufficient_at")
    if last != list(bucket):  # JSON deserialises tuples as lists — normalise
        print(
            f"[WHEEL] Insufficient buying power: ${bp:.2f} < ${required:.2f} "
            f"({label}) — skipping cycle"
        )
        state["last_logged_insufficient_at"] = list(bucket)
    return True


# ── CSP helper functions (unchanged from original) ───────────────────────────

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


# ── shared helpers ────────────────────────────────────────────────────────────

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


def _fetch_option_chain(symbol: str, price: float, cfg) -> dict | None:
    """Fetch the option chain from Alpaca and reformat it for best_bull_put_spread."""
    from datetime import timedelta
    from alpaca.trading.requests import GetOptionContractsRequest
    from alpaca.trading.enums import ContractType

    today = date.today()
    min_exp = today + timedelta(days=cfg.target_dte_min)
    max_exp = today + timedelta(days=cfg.target_dte_max)

    target_short = price * (1.0 - cfg.target_otm_pct)
    min_strike = target_short - cfg.spread_width - 1  # room for long leg
    max_strike = target_short + 1                     # one notch above target

    try:
        client = alpaca_client.trading()
        contracts = client.get_option_contracts(GetOptionContractsRequest(
            underlying_symbols=[symbol],
            status="active",
            type=ContractType.PUT,
            expiration_date_gte=min_exp,
            expiration_date_lte=max_exp,
            strike_price_gte=str(round(min_strike, 2)),
            strike_price_lte=str(round(max_strike, 2)),
        ))
    except Exception as e:
        print(f"[WHEEL] Option chain fetch failed: {e}")
        return None

    if not contracts.option_contracts:
        print(f"[WHEEL] No contracts found in chain for {symbol}")
        return None

    # Fetch quotes for all contracts
    data_client = alpaca_client.option_data()
    chain_contracts = []
    for c in contracts.option_contracts:
        try:
            resp = data_client.get_option_latest_quote(
                OptionLatestQuoteRequest(symbol_or_symbols=c.symbol)
            )
            q = resp[c.symbol]
            chain_contracts.append({
                "symbol": c.symbol,
                "type": "put",
                "strike": float(c.strike_price),
                "expiration_date": str(c.expiration_date),
                "bid": float(q.bid_price),
                "ask": float(q.ask_price),
            })
        except Exception:
            continue

    return {"spot_price": price, "contracts": chain_contracts}


def _get_option_quote(contract_sym: str) -> dict | None:
    """Return {'bid': float, 'ask': float} for a contract, or None on failure."""
    try:
        client = alpaca_client.option_data()
        resp = client.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=contract_sym)
        )
        q = resp[contract_sym]
        return {"bid": float(q.bid_price), "ask": float(q.ask_price)}
    except Exception as e:
        print(f"[WHEEL] Quote fetch failed {contract_sym}: {e}")
        return None
