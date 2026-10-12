"""Backtest of the weekly ETF momentum rotation (rotation/), CLAUDE.md §1 gate.

Drives the SAME `rotation.signals.target_weights` the live task uses.
Data: Yahoo adjusted closes in backtest/data/etf/<SYM>.csv (date,close,adjclose),
gitignored; cross-checked against Alpaca SIP adjustment=all (total-return
diff < 1 % over 2016-2026). Cash before BIL existed (2007-05) = SHY.

Rules: signal on the close of the first session of each ISO week, executed on
the NEXT session's close (lag 1 — live trades the morning after the signal
close); weights drift between rebalances; same drift tolerance as live;
cost 0.05 % per side on turnover.

    .venv/bin/python -m backtest.rotation_backtest [--alloc 0.5]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from rotation.config import RotationConfig
from rotation.signals import target_weights

DATA = Path(__file__).parent / "data" / "etf"
FEE = 0.0005


def load_prices(cfg: RotationConfig) -> pd.DataFrame:
    syms = list(cfg.universe) + [cfg.cash_symbol, "SHY"]
    px = pd.concat({s: pd.read_csv(DATA / f"{s}.csv", index_col=0, parse_dates=True)["adjclose"] for s in syms}, axis=1)
    px = px[px.index >= "2003-01-01"].sort_index()
    # Cash proxy before BIL listed: SHY returns spliced in.
    cash_ret = px[cfg.cash_symbol].pct_change().where(px[cfg.cash_symbol].notna(), px["SHY"].pct_change())
    px[cfg.cash_symbol] = (1 + cash_ret.fillna(0)).cumprod()
    return px.drop(columns="SHY")


def simulate(cfg: RotationConfig, px: pd.DataFrame, start="2007-03-01", alloc=1.0) -> pd.Series:
    ret = px.pct_change().fillna(0.0)
    idx = px.index
    weeks = pd.Series(idx, index=idx).groupby([idx.isocalendar().year, idx.isocalendar().week]).first()
    signal_days = set(weeks.values)
    w = pd.Series(0.0, index=px.columns)
    eq, out, pending = 1.0, [], None
    for i, d in enumerate(idx):
        r = ret.loc[d]
        sleeve = float((w * r).sum())
        eq *= 1 + alloc * sleeve            # the (1 - alloc) remainder sits in cash at 0 %
        g = w * (1 + r)
        w = g / g.sum() if g.sum() > 0 else w
        if pending is not None:
            new = pending
            diff = new - w
            # live drift tolerance: leave held names that are close to target
            keep = (w > 0) & (new > 0) & (diff.abs() <= cfg.drift_tol * new)
            new = new.where(~keep, w)
            new = new / new.sum()
            eq *= 1 - alloc * FEE * (new - w).abs().sum()
            w, pending = new, None
        if d >= pd.Timestamp(start) - pd.Timedelta(days=10) and d in signal_days:
            hist = {s: px[s].iloc[: i + 1].dropna().tolist() for s in cfg.universe}
            tw = target_weights(hist, cfg)
            pending = pd.Series(0.0, index=px.columns)
            for k, v in tw.items():
                pending[k] = v
        if d >= pd.Timestamp(start):
            out.append((d, eq))
    s = pd.Series(dict(out))
    return s / s.iloc[0]


def metrics(eq: pd.Series) -> dict:
    r = eq.pct_change().dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    return {"CAGR %": round(cagr * 100, 1), "MaxDD %": round(dd * 100, 1),
            "Sharpe": round(r.mean() / r.std() * np.sqrt(252), 2) if r.std() > 0 else 0.0,
            "Calmar": round(cagr / -dd, 2) if dd < 0 else np.nan}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alloc", type=float, default=1.0, help="share of the account in the sleeve")
    a = ap.parse_args()
    cfg = RotationConfig()
    px = load_prices(cfg)
    rot = simulate(cfg, px, alloc=a.alloc)
    spy = (px["SPY"] / px["SPY"].loc[rot.index[0]]).reindex(rot.index)
    rows = {}
    for name, eq in (("rotation", rot), ("buy&hold SPY", spy)):
        for wn, (s, e) in {"IS 2007-03→2021": ("2007-03-01", "2021-12-31"),
                           "OOS 2022→": ("2022-01-01", "2100-01-01"),
                           "FULL": ("2007-03-01", "2100-01-01")}.items():
            rows[(name, wn)] = metrics(eq[(eq.index >= s) & (eq.index <= e)])
    print(pd.DataFrame(rows).T.to_string())
    yr = pd.DataFrame({"rotation": rot, "SPY": spy}).resample("YE").last().pct_change().mul(100).round(1)
    yr.index = yr.index.year
    print(yr.to_string())


if __name__ == "__main__":
    main()
