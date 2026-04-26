"""
Capitol Trades BFF API — same endpoint their frontend uses.
Source: https://github.com/TommasoAmici/capitoltrades

Base:      https://bff.capitoltrades.com
Endpoints: /trades  /politicians  /issuers/{id}

Trade fields (from Rust types):
  txId | pubDate | txDate | txType | politician.name
  asset.assetTicker | sizeRangeLow | sizeRangeHigh | value
"""
import time
import httpx

_BASE = "https://bff.capitoltrades.com"

_HEADERS = {
    "accept":           "*/*",
    "accept-language":  "en-US,en;q=0.9",
    "content-type":     "application/json",
    "origin":           "https://www.capitoltrades.com",
    "referer":          "https://www.capitoltrades.com",
    "sec-fetch-dest":   "empty",
    "sec-fetch-mode":   "cors",
    "sec-fetch-site":   "same-site",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def fetch_trades(pages: int = 3) -> list[dict]:
    trades: list[dict] = []
    with httpx.Client(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        for page in range(pages):
            data = _get_page(client, page)
            if data is None:
                break
            for item in data:
                t = _normalize(item)
                if t:
                    trades.append(t)
            print(f"[SCRAPER] Page {page}: {len(data)} trades")

    print(f"[SCRAPER] Total: {len(trades)} trades fetched")
    return trades


def _get_page(client: httpx.Client, page: int, retries: int = 3) -> list | None:
    delay = 5
    for attempt in range(retries):
        try:
            r = client.get(f"{_BASE}/trades", params={"page": page, "pageSize": 100})
            r.raise_for_status()
            return r.json().get("data", [])
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code in (429, 503, 502) and attempt < retries - 1:
                print(f"[SCRAPER] HTTP {code} — retry {attempt + 1}/{retries} in {delay}s")
                time.sleep(delay)
                delay *= 2
            else:
                print(f"[SCRAPER] HTTP {code} — giving up on page {page}")
                return None
        except Exception as e:
            print(f"[SCRAPER] Error page {page}: {e}")
            return None
    return None


def fetch_politicians() -> list[dict]:
    """Returns list of politicians with id and name for scorer."""
    politicians = []
    with httpx.Client(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        try:
            r = client.get(f"{_BASE}/politicians", params={"pageSize": 100})
            r.raise_for_status()
            data = r.json().get("data", [])
            for p in data:
                politicians.append({
                    "id":   p.get("politicianId") or p.get("id"),
                    "name": p.get("name") or p.get("fullName", "Unknown"),
                })
        except Exception as e:
            print(f"[SCRAPER] Politicians fetch error: {e}")
    return politicians


def _normalize(item: dict) -> dict | None:
    asset  = item.get("asset") or {}
    ticker = (asset.get("assetTicker") or "").strip().upper()
    if not ticker or ticker in ("--", "N/A", ""):
        return None

    politician = item.get("politician") or {}
    name = (
        politician.get("name")
        or politician.get("fullName")
        or item.get("politicianName")
        or "Unknown"
    )

    tx_type = (item.get("txType") or item.get("tx_type") or "").lower()
    side = "buy" if any(w in tx_type for w in ("purchase", "buy")) else "sell"

    return {
        "id":          str(item.get("txId") or item.get("_txId") or item.get("tx_id", "")),
        "politician":  name,
        "ticker":      ticker,
        "type":        side,
        "traded_date": str(item.get("txDate") or item.get("tx_date", "")),
        "pub_date":    str(item.get("pubDate") or item.get("pub_date", "")),
        "amount_low":  item.get("sizeRangeLow")  or item.get("size_range_low"),
        "amount_high": item.get("sizeRangeHigh") or item.get("size_range_high"),
    }
