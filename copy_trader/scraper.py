"""
Capitol Trades HTML scraper.
Parses the trades table directly from www.capitoltrades.com/trades.
No API key required. Each page yields ~12 trades (SSR, page 0 only).
"""
import re
import time
import hashlib
import httpx
from datetime import datetime

_BASE = "https://www.capitoltrades.com"

_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

_PARTY_RE = re.compile(r"(Republican|Democrat|Independent|Libertarian)")
_TICKER_RE = re.compile(r"([A-Z]{1,6}):[A-Z]{2,3}$")
_DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]{3})(\d{4})")


def fetch_trades(pages: int = 1) -> list[dict]:
    trades: list[dict] = []
    with httpx.Client(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        html = _get_html(client)
        if html is None:
            print("[SCRAPER] Failed to fetch Capitol Trades page")
            return trades

        ids = _extract_trade_ids(html)
        cells = _extract_cells(html)

        rows = [cells[i:i+10] for i in range(0, len(cells) - 9, 10)]
        print(f"[SCRAPER] Parsed {len(rows)} trades from Capitol Trades")

        for i, row in enumerate(rows):
            t = _parse_row(row, ids[i] if i < len(ids) else None)
            if t:
                trades.append(t)

    return trades


def _get_html(client: httpx.Client, retries: int = 3) -> str | None:
    delay = 5
    for attempt in range(retries):
        try:
            r = client.get(f"{_BASE}/trades")
            r.raise_for_status()
            return r.text
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code in (429, 502, 503) and attempt < retries - 1:
                print(f"[SCRAPER] HTTP {code} — retry {attempt + 1}/{retries} in {delay}s")
                time.sleep(delay)
                delay *= 2
            else:
                print(f"[SCRAPER] HTTP {code} — giving up")
                return None
        except Exception as e:
            print(f"[SCRAPER] Error: {e}")
            return None
    return None


def _extract_trade_ids(html: str) -> list[str]:
    return re.findall(r'/trades/(\d+)', html)


def _extract_cells(html: str) -> list[str]:
    tds = re.findall(r'<td[^>]*>(.+?)</td>', html, re.DOTALL)
    return [re.sub(r'<[^>]+>', '', td).replace('&amp;', '&').strip() for td in tds]


def _parse_row(row: list[str], trade_id: str | None) -> dict | None:
    if len(row) < 9:
        return None

    politician_raw = row[0]
    asset_raw = row[1]
    pub_date_raw = row[2]
    tx_date_raw = row[3]
    tx_type_raw = row[6].lower()
    amount_raw = row[7]

    # Extract politician name (everything before party keyword)
    m = _PARTY_RE.search(politician_raw)
    politician = politician_raw[:m.start()].strip() if m else politician_raw

    # Extract ticker from "Company NameTICKER:US"
    tm = _TICKER_RE.search(asset_raw)
    if not tm:
        return None
    ticker = tm.group(1)

    # Normalize transaction type
    side = "buy" if "buy" in tx_type_raw or "purchase" in tx_type_raw else "sell"

    tx_date = _parse_date(tx_date_raw)
    pub_date = _parse_date(pub_date_raw)

    # Stable ID: use trade page ID if available, else hash
    tid = trade_id or hashlib.md5(f"{politician}{ticker}{tx_date}".encode()).hexdigest()[:12]

    return {
        "id": tid,
        "politician": politician,
        "ticker": ticker,
        "type": side,
        "traded_date": tx_date,
        "pub_date": pub_date,
        "amount_low": amount_raw,
        "amount_high": amount_raw,
    }


def _parse_date(raw: str) -> str:
    m = _DATE_RE.search(raw)
    if not m:
        return ""
    try:
        dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %b %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return ""
