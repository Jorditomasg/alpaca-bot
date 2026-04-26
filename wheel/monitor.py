"""
50% profit rule: if open option is worth ≤ 50% of premium received,
close it early (buy to close) and trigger a new sell.
"""
import alpaca_client
import wheel.options as options_mod
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce


def check_early_close(state: dict) -> dict:
    stage = state["stage"]
    if stage not in ("PUT_OPEN", "CALL_OPEN"):
        return state

    contract_sym = state.get("contract_symbol")
    if not contract_sym:
        return state

    current_price = options_mod.get_quote(contract_sym)
    if current_price is None:
        return state

    original_premium_per_share = state["premium_received"] / 100
    if current_price <= original_premium_per_share * 0.50:
        print(f"[MONITOR] 50% profit reached on {contract_sym} "
              f"(paid ${original_premium_per_share:.2f}, now ${current_price:.2f}) → closing early")
        _buy_to_close(contract_sym)
        # Reset to trigger new sell on next engine run
        state["contract_symbol"] = None
        if stage == "PUT_OPEN":
            state["stage"] = "IDLE"
        elif stage == "CALL_OPEN":
            state["stage"] = "ASSIGNED"

    return state


def _buy_to_close(contract_sym: str) -> None:
    client = alpaca_client.trading()
    try:
        client.submit_order(MarketOrderRequest(
            symbol=contract_sym,
            qty=1,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        ))
        print(f"[MONITOR] Buy-to-close submitted: {contract_sym}")
    except Exception as e:
        print(f"[MONITOR] Buy-to-close failed: {e}")
