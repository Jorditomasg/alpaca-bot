"""
Selects the best option contract to sell for the wheel strategy.
PUT  : ~10% OTM, 2-4 weeks out, highest premium
CALL : ~10% above cost_basis, 2-4 weeks out, highest premium
"""
from datetime import date, timedelta
from shared import alpaca_client
from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.trading.enums import ContractType
from alpaca.data.requests import OptionLatestQuoteRequest


def best_put(symbol: str, current_price: float) -> dict | None:
    target_strike = round(current_price * 0.90, 0)
    return _find_contract(symbol, ContractType.PUT, target_strike)


def best_call(symbol: str, cost_basis: float) -> dict | None:
    target_strike = round(cost_basis * 1.10, 0)
    return _find_contract(symbol, ContractType.CALL, target_strike)


def get_quote(contract_symbol: str) -> float | None:
    try:
        client = alpaca_client.option_data()
        resp = client.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=contract_symbol)
        )
        q = resp[contract_symbol]
        return float((q.bid_price + q.ask_price) / 2)
    except Exception as e:
        print(f"[OPTIONS] Quote failed {contract_symbol}: {e}")
        return None


def _find_contract(symbol: str, contract_type: ContractType, target_strike: float) -> dict | None:
    today = date.today()
    min_exp = today + timedelta(days=14)
    max_exp = today + timedelta(days=28)

    try:
        client = alpaca_client.trading()
        contracts = client.get_option_contracts(GetOptionContractsRequest(
            underlying_symbols=[symbol],
            status="active",
            type=contract_type,
            expiration_date_gte=min_exp,
            expiration_date_lte=max_exp,
            strike_price_gte=str(target_strike - 5),
            strike_price_lte=str(target_strike + 5),
        ))
    except Exception as e:
        print(f"[OPTIONS] Contract search failed: {e}")
        return None

    if not contracts.option_contracts:
        print(f"[OPTIONS] No contracts found near ${target_strike} for {symbol}")
        return None

    # Pick the contract with highest midpoint premium
    best = None
    best_premium = -1.0
    data_client = alpaca_client.option_data()

    for c in contracts.option_contracts:
        try:
            resp = data_client.get_option_latest_quote(
                OptionLatestQuoteRequest(symbol_or_symbols=c.symbol)
            )
            q = resp[c.symbol]
            mid = float((q.bid_price + q.ask_price) / 2)
            if mid > best_premium:
                best_premium = mid
                best = {"symbol": c.symbol, "strike": float(c.strike_price),
                        "expiry": str(c.expiration_date), "premium": mid}
        except Exception:
            continue

    return best
