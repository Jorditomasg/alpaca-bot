"""Live rotation rebalance — I/O shell around the pure signals/rebalance modules.

Everything that touches the broker is injected so tests/unit/test_rotation_engine.py
can drive it without a network.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from rotation.config import RotationConfig
from rotation.rebalance import plan_orders, rotation_budget
from rotation.signals import target_weights


@dataclass
class Broker:
    """The broker calls the rotation needs. Defaults bind to the real Alpaca helpers."""
    account: Callable[[], dict]                       # {"equity", "cash"}
    positions: Callable[[], dict[str, tuple[float, float]]]   # sym → (qty, market_value)
    closes: Callable[[list[str], date], dict[str, list[float]]]
    buy: Callable[..., object]
    sell: Callable[..., object]
    close_position: Callable[[str], object]
    sleep: Callable[[float], None] = field(default=time.sleep)


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def due(state: dict, today: date) -> bool:
    """One rebalance per ISO week (the backtest rebalances weekly)."""
    return state.get("last_rebalance_week") != iso_week(today)


def run_rebalance(
    cfg: RotationConfig,
    broker: Broker,
    today: date,
    exclude: set[str],
    halted: bool,
    log: Callable[[str], None] = print,
) -> dict:
    """Compute targets from the last CLOSED session and trade the difference.

    Returns ``{"weights", "orders", "budget"}`` for state + notifications.
    Buys are skipped while the kill switch is halted; sells always run (§7).
    """
    syms = sorted(set(cfg.universe) | {cfg.cash_symbol})
    closes = broker.closes(syms, today)
    weights = target_weights(closes, cfg, exclude=exclude)

    acct = broker.account()
    held = {s: v for s, v in broker.positions().items() if s in syms and s not in exclude}
    current = {s: mv for s, (qty, mv) in held.items()}
    held_qty = {s: qty for s, (qty, mv) in held.items()}
    budget = rotation_budget(acct["equity"], acct["cash"], sum(current.values()),
                             cfg.alloc_pct, cfg.reserve_pct)
    orders = plan_orders(current, held_qty, weights, budget, cfg.min_trade, cfg.drift_tol)
    log(f"[ROTATION] targets={ {k: round(v, 3) for k, v in weights.items()} } "
        f"budget=${budget:.2f} held=${sum(current.values()):.2f} orders={len(orders)}")

    done = []
    sells = [o for o in orders if o[0] == "SELL"]
    buys = [o for o in orders if o[0] == "BUY"]
    for _, sym, amt in sells:
        try:
            if "qty" in amt:
                broker.close_position(sym)       # full exit: no fractional dust
            else:
                broker.sell(sym, notional=amt["notional"])
            done.append(("SELL", sym, amt))
        except Exception as e:
            log(f"[ROTATION] SELL {sym} failed: {e}")
    if sells and buys:
        broker.sleep(5)                          # let market sells fill before spending
    if halted and buys:
        log("[ROTATION] Kill switch active — skipping buys")
        buys = []
    for _, sym, amt in buys:
        try:
            broker.buy(sym, notional=amt["notional"])
            done.append(("BUY", sym, amt))
        except Exception as e:
            log(f"[ROTATION] BUY {sym} ${amt['notional']:.2f} failed: {e}")
    return {"weights": weights, "orders": done, "budget": budget}


# ── Real Alpaca bindings ────────────────────────────────────────────────────

def alpaca_broker() -> Broker:
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from shared import alpaca_client
    from shared import trader as shared_trader

    def account() -> dict:
        a = alpaca_client.trading().get_account()
        # min(cash, buying_power): never lean on margin, and respect cash
        # locked as option collateral (the wheel's spread).
        return {"equity": float(a.equity), "cash": min(float(a.cash), float(a.buying_power))}

    def positions() -> dict:
        out = {}
        for p in alpaca_client.trading().get_all_positions():
            if getattr(p, "asset_class", None) and "option" in str(p.asset_class):
                continue
            out[p.symbol] = (float(p.qty), float(p.market_value))
        return out

    def closes(symbols: list[str], today: date) -> dict[str, list[float]]:
        """Split/dividend-adjusted daily closes up to the last session BEFORE today."""
        start = datetime.now(timezone.utc) - timedelta(days=520)
        end = datetime.now(timezone.utc) - timedelta(minutes=20)   # free SIP: 15-min delay
        client = alpaca_client.stock_data()
        out: dict[str, list[float]] = {}
        for feed in (DataFeed.SIP, DataFeed.IEX):
            try:
                resp = client.get_stock_bars(StockBarsRequest(
                    symbol_or_symbols=symbols, timeframe=TimeFrame.Day, start=start, end=end,
                    adjustment=Adjustment.ALL, feed=feed,
                ))
                for sym in symbols:
                    bars = resp.data.get(sym, [])
                    out[sym] = [float(b.close) for b in bars
                                if b.timestamp.astimezone(timezone.utc).date() < today]
                return out
            except Exception as e:
                print(f"[ROTATION] bars via {feed} failed: {e}")
        return out

    return Broker(account=account, positions=positions, closes=closes,
                  buy=shared_trader.buy, sell=shared_trader.sell,
                  close_position=shared_trader.close_position)


def market_open_now() -> bool:
    """Alpaca's clock knows holidays and half-days; market_hours does not (audit §7)."""
    from shared import alpaca_client
    try:
        return bool(alpaca_client.trading().get_clock().is_open)
    except Exception as e:
        print(f"[ROTATION] clock query failed: {e}")
        return False
