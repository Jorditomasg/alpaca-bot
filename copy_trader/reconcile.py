"""Broker ↔ local state reconciliation.

Two jobs:
  1. Drop phantom positions — entries in `state["positions"]` that the broker
     has no record of. These come from old code that added to local state
     before submitting the order, then never cleaned up after a rejected fill.
  2. Backfill metadata for surviving positions — when broker reports a
     position we tracked but without entry_date/cost_basis (legacy schema),
     stamp it from `avg_entry_price` so the exits module can evaluate it.

Fail-safe: on any broker error, leave state untouched. We never delete based
on a failed query — a transient API outage must not wipe positions.
"""
from __future__ import annotations
from datetime import datetime, timezone

from shared import alpaca_client


def with_broker(state: dict) -> None:
    positions = state.get("positions") or {}
    if not positions:
        return

    try:
        client = alpaca_client.trading()
        broker_positions = client.get_all_positions()
    except Exception as e:
        print(f"[RECONCILE] Broker query failed, leaving state intact: {e}")
        return

    broker_map: dict[str, float] = {}
    for bp in broker_positions:
        try:
            broker_map[bp.symbol] = float(bp.avg_entry_price)
        except (AttributeError, TypeError, ValueError):
            continue

    # Phase 1: drop phantoms
    dropped = [t for t in positions.keys() if t not in broker_map]
    for ticker in dropped:
        print(f"[RECONCILE] Dropping phantom position {ticker} — not at broker")
        positions.pop(ticker, None)

    # Phase 2: backfill metadata where missing
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for ticker, pos in positions.items():
        avg_entry = broker_map.get(ticker)
        if avg_entry is None or avg_entry <= 0:
            continue
        if "cost_basis" not in pos:
            pos["cost_basis"] = avg_entry
        if "high_watermark" not in pos:
            pos["high_watermark"] = max(pos.get("cost_basis", avg_entry), avg_entry)
        if "entry_date" not in pos:
            pos["entry_date"] = today
