"""
Given all scraped trades and the current state, returns list of new
trades to copy (not yet seen, from the followed politician).
Options trades are translated to their underlying stock.
"""
import re

_OPTION_UNDERLYING_RE = re.compile(r'^([A-Z]+)')


def new_trades_to_copy(
    trades: list[dict],
    following: str,
    seen_ids: list[str],
) -> list[dict]:
    politician_trades = [
        t for t in trades
        if t["politician"].lower() == following.lower()
        and t["id"] not in seen_ids
    ]

    result = []
    for t in politician_trades:
        ticker = t["ticker"]
        # Translate option tickers to underlying (OCC format: SYMBOL+YYMMDD+C/P+STRIKE)
        if len(ticker) > 5 or any(c.isdigit() for c in ticker):
            m = _OPTION_UNDERLYING_RE.match(ticker)
            if not m:
                print(f"[COPIER] Could not parse option ticker '{ticker}' — skipping")
                continue
            ticker = m.group(1)
            print(f"[COPIER] Option detected → translating to underlying: {ticker}")

        result.append({**t, "ticker": ticker})

    if result:
        print(f"[COPIER] {len(result)} new trade(s) to copy from {following}")
    return result
