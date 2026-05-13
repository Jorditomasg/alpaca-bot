"""Backtest runner — loads PTRs, runs baseline + improved, prints comparison.

Usage:
    python -m backtest.runner \
        --start 2018-01-01 --end 2020-12-31 \
        --politician "Thomas R Carper" \
        --cash 100000 --notional 5000

Picks default politician by most trades in window if none provided.
"""
from __future__ import annotations
import argparse
import os
import pathlib
import sys
from collections import Counter
from datetime import datetime
from dotenv import load_dotenv

from backtest import data as bt_data
from backtest import prices as bt_prices
from backtest import engine as bt_engine
from backtest import strategy as bt_strategy
from backtest import metrics as bt_metrics
from backtest.alpaca_source import fetch_bars


_REPO = pathlib.Path(__file__).resolve().parent.parent
_DATA_FILE = _REPO / "backtest" / "data" / "senate_all.json"
_CACHE_DIR = _REPO / "backtest" / "data" / "price_cache"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end",   default="2020-12-31")
    parser.add_argument("--politician", default=None,
                        help="Politician to follow; default = most active in window")
    parser.add_argument("--cash", type=float, default=100000.0)
    parser.add_argument("--notional", type=float, default=5000.0,
                        help="Notional per copy trade")
    parser.add_argument("--min-amount", type=int, default=15000,
                        help="Improved: minimum politician trade amount to copy")
    parser.add_argument("--freshness-days", type=int, default=14)
    parser.add_argument("--stop-loss", type=float, default=8.0)
    parser.add_argument("--trail-arm", type=float, default=8.0)
    parser.add_argument("--trail-giveback", type=float, default=5.0)
    parser.add_argument("--max-holding", type=int, default=90)
    args = parser.parse_args()

    load_dotenv(_REPO / ".env")
    if not os.environ.get("ALPACA_API_KEY"):
        print("ALPACA_API_KEY not set — backtest needs it for historical bars.")
        return 1

    print(f"[BT] Loading PTRs from {_DATA_FILE}")
    trades = bt_data.load_ptrs(_DATA_FILE)
    print(f"[BT] Loaded {len(trades)} normalized trades")

    # Restrict to the window
    in_window = [t for t in trades if args.start <= t["pub_date"] <= args.end]
    print(f"[BT] In window [{args.start}, {args.end}]: {len(in_window)} trades")

    politician = args.politician or _pick_most_active(in_window)
    print(f"[BT] Following politician: {politician}")

    relevant = [t for t in in_window if t["politician"] == politician]
    print(f"[BT] {politician} has {len(relevant)} trades in window")

    fetcher = bt_prices.PriceFetcher(
        cache_dir=_CACHE_DIR,
        source=fetch_bars,
        history_start=_back_off(args.start, days=10),
        history_end=_forward_pad(args.end, days=10),
    )

    print("[BT] Running BASELINE …")
    baseline = bt_strategy.BaselineStrategy(
        starting_cash=args.cash,
        notional_per_trade=args.notional,
    )
    baseline.set_following(politician)
    r_base = bt_engine.run(relevant, fetcher, baseline, args.start, args.end)
    s_base = bt_metrics.summarize(
        r_base, [t for t in r_base.portfolio.trades_log if t["side"] == "sell"]
    )

    print("[BT] Running IMPROVED …")
    improved = bt_strategy.ImprovedStrategy(
        starting_cash=args.cash,
        notional_per_trade=args.notional,
        pub_freshness_days=args.freshness_days,
        min_amount=args.min_amount,
        stop_loss_pct=args.stop_loss,
        trail_arm_pct=args.trail_arm,
        trail_giveback_pct=args.trail_giveback,
        max_holding_days=args.max_holding,
    )
    improved.set_following(politician)
    r_imp = bt_engine.run(relevant, fetcher, improved, args.start, args.end)
    s_imp = bt_metrics.summarize(
        r_imp, [t for t in r_imp.portfolio.trades_log if t["side"] == "sell"]
    )

    _print_comparison(s_base, s_imp, politician, args.start, args.end)
    return 0


def _pick_most_active(trades: list[dict]) -> str:
    counts = Counter(t["politician"] for t in trades)
    return counts.most_common(1)[0][0]


def _back_off(date_iso: str, days: int) -> str:
    from datetime import timedelta
    d = datetime.strptime(date_iso, "%Y-%m-%d")
    return (d - timedelta(days=days)).strftime("%Y-%m-%d")


def _forward_pad(date_iso: str, days: int) -> str:
    from datetime import timedelta
    d = datetime.strptime(date_iso, "%Y-%m-%d")
    return (d + timedelta(days=days)).strftime("%Y-%m-%d")


def _print_comparison(base: dict, imp: dict, politician: str, start: str, end: str) -> None:
    def pct(x): return f"{x:+.2f}%"
    def num(x): return f"{x:,.2f}"
    def ratio(x): return f"{x:.2f}"

    print()
    print("=" * 70)
    print(f"BACKTEST  |  Politician: {politician}  |  {start} → {end}")
    print("=" * 70)
    print(f"{'Metric':<22} {'Baseline':>20} {'Improved':>20}   Δ")
    print("-" * 70)

    rows = [
        ("Starting equity",     num(base['starting_equity']), num(imp['starting_equity']), None),
        ("Ending equity",       num(base['ending_equity']),   num(imp['ending_equity']),   None),
        ("Total return",        pct(base['total_return_pct']), pct(imp['total_return_pct']),
         imp['total_return_pct'] - base['total_return_pct']),
        ("CAGR",                pct(base['cagr_pct']),         pct(imp['cagr_pct']),
         imp['cagr_pct'] - base['cagr_pct']),
        ("Max drawdown",        pct(base['max_drawdown_pct']), pct(imp['max_drawdown_pct']),
         imp['max_drawdown_pct'] - base['max_drawdown_pct']),
        ("Sharpe (ann)",        ratio(base['sharpe']),         ratio(imp['sharpe']),
         imp['sharpe'] - base['sharpe']),
        ("Closed trades",       str(base['n_closed_trades']),  str(imp['n_closed_trades']),  None),
        ("Win rate",            f"{base['win_rate']*100:.1f}%",
                                f"{imp['win_rate']*100:.1f}%",
         (imp['win_rate'] - base['win_rate']) * 100),
        ("Avg holding days",    f"{base['avg_holding_days']:.0f}",
                                f"{imp['avg_holding_days']:.0f}",
         imp['avg_holding_days'] - base['avg_holding_days']),
    ]
    for label, a, b, delta in rows:
        d = f"  {delta:+.2f}" if isinstance(delta, (int, float)) else ""
        print(f"{label:<22} {a:>20} {b:>20}{d}")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(main())
