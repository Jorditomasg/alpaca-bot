"""Daily summary logged at market close (16:00 ET).

Supports both CSP mode and bull-put-spread mode.
"""
from datetime import datetime
from shared import alpaca_client
from alpaca.data.requests import StockLatestTradeRequest


def print_summary(wheel_state: dict) -> None:
    strategy = wheel_state.get("strategy_type", "csp")
    if strategy == "bull_put_spread":
        _print_spread_summary(wheel_state)
    else:
        _print_csp_summary(wheel_state)


# ── CSP summary (original behaviour) ─────────────────────────────────────────

def _print_csp_summary(wheel_state: dict) -> None:
    symbol  = wheel_state["symbol"]
    stage   = wheel_state["stage"]
    total_p = wheel_state["total_premium"]
    cycles  = wheel_state["cycles"]

    # Current stock price for unrealised P&L
    stock_price = None
    try:
        client = alpaca_client.stock_data()
        resp = client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=symbol)
        )
        stock_price = float(resp[symbol].price)
    except Exception:
        pass

    unrealised = 0.0
    if wheel_state["stage"] in ("ASSIGNED", "CALL_OPEN") and stock_price:
        cb = wheel_state.get("cost_basis") or stock_price
        unrealised = (stock_price - cb) * wheel_state["shares_owned"]

    total_return = total_p + unrealised

    print("\n" + "=" * 56)
    print(f"  WHEEL STRATEGY — DAILY SUMMARY  {datetime.now().strftime('%Y-%m-%d')}")
    print("=" * 56)
    print(f"  Symbol         : {symbol}")
    print(f"  Stage          : {stage}")
    print(f"  Cycles         : {cycles}")
    print(f"  Total premium  : ${total_p:.2f}")
    print(f"  Unrealised P&L : ${unrealised:.2f}")
    print(f"  Total return   : ${total_return:.2f}")
    if wheel_state.get("contract_symbol"):
        print(f"  Open contract  : {wheel_state['contract_symbol']}")
        print(f"  Strike         : ${wheel_state['contract_strike']}")
        print(f"  Expiry         : {wheel_state['contract_expiry']}")
    print("=" * 56 + "\n")


# ── Spread summary ────────────────────────────────────────────────────────────

def _print_spread_summary(wheel_state: dict) -> None:
    symbol  = wheel_state["symbol"]
    stage   = wheel_state["stage"]
    total_p = wheel_state["total_premium"]
    cycles  = wheel_state["cycles"]

    net_credit = wheel_state.get("net_credit", 0.0)
    max_loss   = wheel_state.get("max_loss", 0.0)

    # Try to compute current spread mid-price for unrealised P&L
    current_mid = None
    unrealised_pnl = None
    if stage == "SPREAD_OPEN":
        short_sym = wheel_state.get("short_symbol")
        long_sym  = wheel_state.get("long_symbol")
        if short_sym and long_sym:
            try:
                from alpaca.data.requests import OptionLatestQuoteRequest
                client = alpaca_client.option_data()

                short_resp = client.get_option_latest_quote(
                    OptionLatestQuoteRequest(symbol_or_symbols=short_sym)
                )
                long_resp = client.get_option_latest_quote(
                    OptionLatestQuoteRequest(symbol_or_symbols=long_sym)
                )
                short_bid = float(short_resp[short_sym].bid_price)
                long_ask  = float(long_resp[long_sym].ask_price)
                from wheel.spreads import spread_mid_price
                current_mid = spread_mid_price(short_bid, long_ask)
                # Unrealised P&L: credit received minus current cost to close (per spread)
                unrealised_pnl = (net_credit / 100.0 - current_mid) * 100.0
            except Exception:
                pass

    print("\n" + "=" * 56)
    print(f"  WHEEL STRATEGY (BULL PUT SPREAD) — {datetime.now().strftime('%Y-%m-%d')}")
    print("=" * 56)
    print(f"  Symbol         : {symbol}")
    print(f"  Stage          : {stage}")
    print(f"  Cycles         : {cycles}")
    print(f"  Total premium  : ${total_p:.2f}")

    if stage == "SPREAD_OPEN":
        print(f"  Short leg      : {wheel_state.get('short_symbol', 'n/a')} @ ${wheel_state.get('short_strike', 0):.2f}")
        print(f"  Long leg       : {wheel_state.get('long_symbol', 'n/a')} @ ${wheel_state.get('long_strike', 0):.2f}")
        print(f"  Net credit     : ${net_credit:.2f}")
        print(f"  Max loss       : ${max_loss:.2f}")
        print(f"  Expiry         : {wheel_state.get('contract_expiry', 'n/a')}")
        if current_mid is not None:
            print(f"  Current mid    : ${current_mid:.4f}/share")
        if unrealised_pnl is not None:
            print(f"  Unrealised P&L : ${unrealised_pnl:.2f}")

    print("=" * 56 + "\n")
