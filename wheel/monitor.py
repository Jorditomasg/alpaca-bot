"""
50% profit rule for the wheel strategy (both CSP and bull-put-spread modes).

CSP mode:
  If open option is worth ≤ 50% of premium received → buy-to-close early.

Spread mode (bull_put_spread):
  Spread mid-price = short_bid - long_ask (conservative: values closing cost,
  not opening credit). This is directional: for a credit spread we SOLD to open,
  the mid-price represents what we'd PAY to close. A lower mid-price means more
  profit. We close when mid ≤ 50% of the net credit received per share.
"""
from alpaca.data.requests import OptionLatestQuoteRequest

from shared import alpaca_client
import wheel.options as options_mod
import wheel.spreads as spreads_mod
from wheel.config import get_config
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce


def check_early_close(state: dict) -> dict:
    strategy = state.get("strategy_type", "csp")
    if strategy == "bull_put_spread":
        return _check_spread_close(state)
    return _check_csp_close(state)


# ── CSP early close (original behaviour, unchanged) ───────────────────────────

def _check_csp_close(state: dict) -> dict:
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


# ── Spread early close ────────────────────────────────────────────────────────

def _check_spread_close(state: dict) -> dict:
    if state["stage"] != "SPREAD_OPEN":
        return state

    short_sym = state.get("short_symbol")
    long_sym  = state.get("long_symbol")
    if not short_sym or not long_sym:
        return state

    # Fetch bid/ask separately for each leg
    short_bid = _get_single_bid(short_sym)
    long_ask  = _get_single_ask(long_sym)

    if short_bid is None or long_ask is None:
        return state

    # Spread mid-price = short_bid - long_ask (conservative closing cost).
    # For a bull put spread we SOLD, this is what we'd pay to close now.
    # A lower value means more profit already realised.
    current_cost_per_share = spreads_mod.spread_mid_price(short_bid, long_ask)

    cfg = get_config()
    net_credit_per_share = state["net_credit"] / 100.0
    # Profit target: close when spread costs ≤ (1 - profit_target_pct/100) * net_credit.
    # At 50% (default): close when mid ≤ 0.50 * net_credit (50% of premium remains).
    profit_target_per_share = (1.0 - cfg.profit_target_pct / 100.0) * net_credit_per_share

    if current_cost_per_share <= profit_target_per_share:
        print(
            f"[MONITOR] Spread profit target reached ({cfg.profit_target_pct}%): "
            f"cost=${current_cost_per_share:.2f} <= target=${profit_target_per_share:.2f} "
            f"- submitting close order"
        )
        close_order = spreads_mod.build_close_order(
            short_sym,
            long_sym,
            round(current_cost_per_share, 2),
        )
        client = alpaca_client.trading()
        try:
            client.submit_order(close_order)
            print(f"[MONITOR] Spread close order submitted for {short_sym}/{long_sym}")
        except Exception as e:
            print(f"[MONITOR] Spread close order failed: {e}")

    return state


# ── quote helpers ─────────────────────────────────────────────────────────────

def _get_single_bid(contract_sym: str) -> float | None:
    try:
        client = alpaca_client.option_data()
        resp = client.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=contract_sym)
        )
        return float(resp[contract_sym].bid_price)
    except Exception:
        return None


def _get_single_ask(contract_sym: str) -> float | None:
    try:
        client = alpaca_client.option_data()
        resp = client.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=contract_sym)
        )
        return float(resp[contract_sym].ask_price)
    except Exception:
        return None


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
