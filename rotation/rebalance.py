"""Pure order planning for the rotation sleeve."""
from __future__ import annotations


def rotation_budget(
    equity: float, cash: float, current_value: float, alloc_pct: float, reserve_pct: float,
) -> float:
    """Dollars the sleeve may hold after this rebalance.

    Target is ``alloc_pct × equity``, but new money can only come from cash
    above the reserve kept for the other strategies (CLAUDE.md §5).
    """
    spendable = max(0.0, cash - reserve_pct * equity)
    return max(0.0, min(alloc_pct * equity, current_value + spendable))


def plan_orders(
    current: dict[str, float],
    held_qty: dict[str, float],
    weights: dict[str, float],
    budget: float,
    min_trade: float,
    drift_tol: float,
) -> list[tuple[str, str, dict]]:
    """Orders to move ``current`` (market value by symbol) to ``weights × budget``.

    Sells come first so their proceeds fund the buys. A name leaving the
    target is sold by its full held quantity (no fractional dust left behind);
    a held name is resized only when off target by more than ``drift_tol``.
    Buys are scaled down so they never exceed the cash the plan frees + the
    budget headroom.
    """
    sells: list[tuple[str, str, dict]] = []
    buys: list[tuple[str, str, float]] = []
    for sym, value in sorted(current.items()):
        if sym not in weights and value > 0:
            sells.append(("SELL", sym, {"qty": held_qty.get(sym, 0.0)}))
    for sym, w in sorted(weights.items()):
        target = w * budget
        have = current.get(sym, 0.0)
        diff = target - have
        if have > 0 and abs(diff) <= drift_tol * target:
            continue
        if abs(diff) < min_trade:
            continue
        if diff < 0:
            sells.append(("SELL", sym, {"notional": round(-diff, 2)}))
        else:
            buys.append(("BUY", sym, diff))

    freed = sum(current.get(s, 0.0) for _, s, a in sells if "qty" in a) + sum(
        a["notional"] for _, _, a in sells if "notional" in a)
    headroom = budget - sum(current.values()) + freed
    want = sum(d for _, _, d in buys)
    scale = min(1.0, headroom / want) if want > 0 else 0.0
    orders = list(sells)
    for side, sym, d in buys:
        amt = round(d * scale, 2)
        if amt >= min_trade:
            orders.append((side, sym, {"notional": amt}))
    return orders
