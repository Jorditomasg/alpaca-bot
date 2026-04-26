"""Daily summary logged at market close (16:00 ET)."""
from datetime import datetime
from shared import alpaca_client
from alpaca.data.requests import StockLatestTradeRequest


def print_summary(wheel_state: dict) -> None:
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
