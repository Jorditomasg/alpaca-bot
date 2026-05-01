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


def score_all_politicians(trades: list[dict]) -> dict[str, float]:
    """Calculates scores for all politicians and returns a mapping."""
    if not trades:
        return {}

    by_politician: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by_politician[t["politician"]].append(t)

    # filter: minimum 3 trades to have a baseline
    eligible = {k: v for k, v in by_politician.items() if len(v) >= 3}
    if not eligible: eligible = by_politician

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
        recent_count = sum(1 for t in ts if _parse_date(t["traded_date"]) >= cutoff_30d)
        
        recency = recent_count / max_recent
        volume = len(ts) / max_volume
        
        # Final Score: Win Rate is king (50%), then Activity (30%) and Volume (20%)
        scores[politician] = win_rate * 0.50 + recency * 0.30 + volume * 0.20

    return scores


def get_consensus_ticker(trades: list[dict]) -> str | None:
    """Finds the stock with the most 'weighted consensus' among politicians."""
    if not trades:
        return None

    # 1. Get quality scores for all politicians
    p_scores = score_all_politicians(trades)
    
    # 2. Count weighted buys per ticker
    ticker_scores: dict[str, float] = defaultdict(float)
    ticker_buyers: dict[str, set] = defaultdict(set)
    
    for t in trades:
        if t["type"] != "buy":
            continue
            
        ticker = t["ticker"]
        pol = t["politician"]
        score = p_scores.get(pol, 0.1) # Default low score for unknown
        
        # Scoring formula: 
        # Each unique politician buying the stock adds their quality score to the total
        if pol not in ticker_buyers[ticker]:
            ticker_scores[ticker] += score
            ticker_buyers[ticker].add(pol)

    if not ticker_scores:
        return None

    # 3. Pick the winner
    best_ticker = max(ticker_scores, key=ticker_scores.__getitem__)
    print(f"[CONSENSUS] Winner: {best_ticker} | Buyers: {len(ticker_buyers[best_ticker])} | Weight: {ticker_scores[best_ticker]:.2f}")
    
    return best_ticker


def score_and_pick(trades: list[dict]) -> str | None:
    """Legacy support: just picks the top politician."""
    scores = score_all_politicians(trades)
    if not scores:
        return None
    top = max(scores, key=scores.__getitem__)
    print(f"[SCORER] Top Politician: {top} | score={scores[top]:.3f}")
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
