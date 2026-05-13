"""Senate Stock Watcher PTR loader.

Normalizes raw senate disclosure JSON into the trades schema used by
copy_trader.copier — so backtest strategies can reuse the production code path.
"""
from __future__ import annotations
import hashlib
import json
import pathlib
import re
from datetime import datetime, timedelta


# Average disclosure delay. STOCK Act allows up to 45 days; politicians who file
# late pay a $200 fine that most are willing to eat. 30 days is a realistic
# midpoint and matches what academic backtests of politician trades use.
DISCLOSURE_DELAY_DAYS = 30

_AMOUNT_RE = re.compile(r"\$([\d,]+)\s*-\s*\$([\d,]+)")


def load_ptrs(path: pathlib.Path) -> list[dict]:
    """Load + normalize Senate PTR transactions.

    Drops:
      - non-stock assets (bonds, options, mutual funds)
      - rows with unparseable transaction_date
      - rows with unparseable amount

    Returns trades sorted oldest-first by pub_date (so the engine can replay
    them chronologically without sorting).
    """
    raw = json.loads(path.read_text())
    out: list[dict] = []
    seen_ids: set[str] = set()

    for i, row in enumerate(raw):
        if row.get("asset_type") != "Stock":
            continue

        traded = _parse_date(row.get("transaction_date", ""))
        if traded is None:
            continue

        amounts = _parse_amount(row.get("amount", ""))
        if amounts is None:
            continue
        low, high = amounts

        side = _classify_side(row.get("type", ""))
        if side is None:
            continue

        ticker = (row.get("ticker") or "").strip().upper()
        if not ticker or ticker == "--":
            continue

        pub = traded + timedelta(days=DISCLOSURE_DELAY_DAYS)

        tid = _make_id(row, i)
        if tid in seen_ids:
            continue
        seen_ids.add(tid)

        out.append({
            "id": tid,
            "politician": row.get("senator", "").strip(),
            "ticker": ticker,
            "type": side,
            "traded_date": traded.strftime("%Y-%m-%d"),
            "pub_date": pub.strftime("%Y-%m-%d"),
            "amount_low": low,
            "amount_high": high,
            "amount_mid": (low + high) / 2,
        })

    out.sort(key=lambda t: t["pub_date"])
    return out


def _parse_date(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%m/%d/%Y")
    except ValueError:
        return None


def _parse_amount(s: str) -> tuple[int, int] | None:
    m = _AMOUNT_RE.search(s)
    if not m:
        return None
    low = int(m.group(1).replace(",", ""))
    high = int(m.group(2).replace(",", ""))
    return low, high


def _classify_side(txn_type: str) -> str | None:
    t = txn_type.lower()
    if "purchase" in t:
        return "buy"
    if "sale" in t:
        return "sell"
    return None


def _make_id(row: dict, idx: int) -> str:
    base = f"{row.get('ptr_link', '')}|{row.get('ticker', '')}|{row.get('transaction_date', '')}|{idx}"
    return hashlib.md5(base.encode()).hexdigest()[:16]
