"""
Scores politicians by combined metric:
  score = win_rate × 0.40 + recency × 0.35 + volume × 0.25

win_rate : fraction of buy trades where ticker is up since filed date
recency  : normalised trades-in-last-30-days count
volume   : normalised total trade count

Returns the top politician's name.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from shared import alpaca_client


def score_and_pick(trades: list[dict]) -> str | None:
    if not trades:
        return None

    by_politician: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by_politician[t["politician"]].append(t)

    # filter: minimum 5 trades to be eligible
    eligible = {k: v for k, v in by_politician.items() if len(v) >= 5}
    if not eligible:
        eligible = by_politician  # relax if not enough data

    cutoff_30d = datetime.utcnow() - timedelta(days=30)
    max_recent = max(
        sum(1 for t in ts if _parse_date(t["traded_date"]) >= cutoff_30d)
        for ts in eligible.values()
    ) or 1
    max_volume = max(len(ts) for ts in eligible.values()) or 1

    scores: dict[str, float] = {}
    for politician, ts in eligible.items():
        buys = [t for t in ts if t["type"] == "buy"]
        win_rate = _calculate_win_rate(buys) if buys else 0.5

        recent_count = sum(
            1 for t in ts if _parse_date(t["traded_date"]) >= cutoff_30d
        )
        recency  = recent_count / max_recent
        volume   = len(ts) / max_volume

        scores[politician] = win_rate * 0.40 + recency * 0.35 + volume * 0.25

    top = max(scores, key=scores.__getitem__)
    print(f"[SCORER] Top: {top} | score={scores[top]:.3f}")
    return top


def _calculate_win_rate(buys: list[dict]) -> float:
    if not buys:
        return 0.5

    tickers = list({t["ticker"] for t in buys})
    try:
        from alpaca.data.requests import StockLatestTradeRequest, StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        client = alpaca_client.stock_data()

        current_resp = client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=tickers)
        )
        current_prices = {sym: float(tr.price) for sym, tr in current_resp.items()}
    except Exception:
        return 0.5

    wins = 0
    evaluated = 0
    for t in buys:
        ticker = t["ticker"]
        traded_date = t.get("traded_date", "")
        if ticker not in current_prices or not traded_date:
            continue

        try:
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame
            bars_resp = client.get_stock_bars(
                StockBarsRequest(
                    symbol_or_symbols=ticker,
                    timeframe=TimeFrame.Day,
                    start=traded_date,
                    limit=1,
                )
            )
            bars = bars_resp.get(ticker, [])
            if not bars:
                continue
            entry_price = float(bars[0].close)
        except Exception:
            continue

        evaluated += 1
        if current_prices[ticker] > entry_price:
            wins += 1

    return (wins / evaluated) if evaluated > 0 else 0.5


def _parse_date(s: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.utcnow() - timedelta(days=90)
