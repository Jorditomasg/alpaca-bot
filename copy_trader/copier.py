"""
Given all scraped trades and the current state, returns list of new
trades to copy (not yet seen, from the followed politician).
Options trades are translated to their underlying stock.

Optional filters reduce noise from low-conviction or stale filings:
  - freshness_days: skip filings whose pub_date is older than N days
  - min_amount: skip filings whose dollar amount (amount_mid) is below threshold
Sells always bypass min_amount — an exit signal should never be filtered out.
"""
import re
from datetime import datetime

_OPTION_UNDERLYING_RE = re.compile(r'^([A-Z]+)')


def seed_seen_ids_for(
    state: dict,
    trades: list[dict],
    politician: str,
) -> None:
    """Mark all currently-visible trades of `politician` as already-seen.

    Used on follow-change so we copy only trades that appear AFTER the switch,
    not the politician's historical positions still visible on the page.
    """
    seen = state.setdefault("seen_trade_ids", [])
    seen_set = set(seen)
    for t in trades:
        if t["politician"].lower() == politician.lower() and t["id"] not in seen_set:
            seen.append(t["id"])
            seen_set.add(t["id"])


def new_trades_to_copy(
    trades: list[dict],
    following: str,
    seen_ids: list[str],
    *,
    today: str | None = None,
    freshness_days: int | None = None,
    min_amount: int | None = None,
) -> list[dict]:
    politician_trades = [
        t for t in trades
        if t["politician"].lower() == following.lower()
        and t["id"] not in seen_ids
    ]

    # Freshness filter — only act on filings within window (sells always pass)
    if freshness_days is not None and today is not None:
        today_dt = datetime.strptime(today, "%Y-%m-%d")
        kept = []
        for t in politician_trades:
            if t.get("type") == "sell":
                kept.append(t)
                continue
            pub = t.get("pub_date")
            if not pub:
                continue
            try:
                age = (today_dt - datetime.strptime(pub, "%Y-%m-%d")).days
            except ValueError:
                continue
            if age <= freshness_days:
                kept.append(t)
        politician_trades = kept

    # Min-amount filter — sells always pass (we never want to skip an exit)
    if min_amount is not None:
        politician_trades = [
            t for t in politician_trades
            if t.get("type") == "sell" or t.get("amount_mid", 0) >= min_amount
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
