"""Operator script: snapshot a live option chain from Alpaca and write it to a JSON fixture.

Usage:
    python -m wheel.tools.capture_chain [SYMBOL]
    python wheel/tools/capture_chain.py [SYMBOL]

Default symbol is taken from WHEEL_SYMBOL env var (falls back to SOFI).

Output file: tests/fixtures/option_chains/<SYMBOL>_<YYYYMMDD>.json

NOTE: Task 7.2 (real capture) is OPERATOR-DEFERRED. This script must be run
manually at least once during regular market hours (09:30–16:00 ET) on a trading
day to produce a real fixture. The file tests/fixtures/option_chains/sofi_synthetic.json
is a synthetic placeholder that allows replay tests to run without a live capture.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from shared import alpaca_client
from wheel.config import get_config
from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.trading.enums import ContractType
from alpaca.data.requests import OptionLatestQuoteRequest, StockLatestTradeRequest


FIXTURES_DIR = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "option_chains"


def capture(symbol: str) -> Path:
    """Fetch the option chain for *symbol* and write it to a dated JSON fixture."""
    cfg = get_config()
    today = date.today()
    min_exp = today + timedelta(days=cfg.target_dte_min)
    max_exp = today + timedelta(days=cfg.target_dte_max)

    # Get spot price
    stock_client = alpaca_client.stock_data()
    spot_resp = stock_client.get_stock_latest_trade(
        StockLatestTradeRequest(symbol_or_symbols=symbol)
    )
    spot_price = float(spot_resp[symbol].price)
    print(f"[CAPTURE] {symbol} spot: ${spot_price:.2f}")

    target_short = spot_price * (1.0 - cfg.target_otm_pct)
    min_strike = target_short - cfg.spread_width - 2
    max_strike = target_short + 2

    trading_client = alpaca_client.trading()
    contracts_resp = trading_client.get_option_contracts(GetOptionContractsRequest(
        underlying_symbols=[symbol],
        status="active",
        type=ContractType.PUT,
        expiration_date_gte=min_exp,
        expiration_date_lte=max_exp,
        strike_price_gte=str(round(min_strike, 2)),
        strike_price_lte=str(round(max_strike, 2)),
    ))

    contracts = contracts_resp.option_contracts
    print(f"[CAPTURE] Found {len(contracts)} contracts")

    # Fetch quotes
    data_client = alpaca_client.option_data()
    chain_contracts = []
    for c in contracts:
        try:
            q_resp = data_client.get_option_latest_quote(
                OptionLatestQuoteRequest(symbol_or_symbols=c.symbol)
            )
            q = q_resp[c.symbol]
            chain_contracts.append({
                "symbol": c.symbol,
                "type": "put",
                "strike": float(c.strike_price),
                "expiration_date": str(c.expiration_date),
                "bid": float(q.bid_price),
                "ask": float(q.ask_price),
            })
        except Exception as e:
            print(f"[CAPTURE] Quote failed for {c.symbol}: {e}")

    fixture = {
        "captured_at": today.isoformat() + "T00:00:00Z",
        "underlying": symbol,
        "spot_price": spot_price,
        "contracts": chain_contracts,
    }

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = FIXTURES_DIR / f"{symbol.lower()}_{today.strftime('%Y%m%d')}.json"
    out_path.write_text(json.dumps(fixture, indent=2))
    print(f"[CAPTURE] Written: {out_path}")
    return out_path


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else os.getenv("WHEEL_SYMBOL", "SOFI")
    capture(symbol.upper())
