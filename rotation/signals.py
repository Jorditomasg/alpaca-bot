"""Pure signal logic — shared by the live engine and backtest/rotation_backtest.py."""
from __future__ import annotations

from rotation.config import RotationConfig


def momentum_score(closes: list[float], lookbacks: tuple[int, ...]) -> float | None:
    """Mean of the trailing total returns over ``lookbacks`` (bars). None if history is short."""
    if not closes or len(closes) <= max(lookbacks):
        return None
    last = closes[-1]
    rets = []
    for k in lookbacks:
        base = closes[-1 - k]
        if base is None or base <= 0:
            return None
        rets.append(last / base - 1.0)
    return sum(rets) / len(rets)


def above_sma(closes: list[float], period: int) -> bool:
    if len(closes) < period:
        return False
    return closes[-1] > sum(closes[-period:]) / period


def target_weights(
    closes: dict[str, list[float]],
    cfg: RotationConfig,
    exclude: set[str] | frozenset[str] = frozenset(),
) -> dict[str, float]:
    """Equal-weight top-N by momentum; a slot below its SMA goes to the cash ETF.

    ``closes`` holds adjusted daily closes, oldest first, ending at the last
    CLOSED session (the decision is made on that close, executed after it).
    ``exclude`` removes symbols another strategy holds, so the rotation never
    trades a position it does not own.
    """
    scores = {}
    for sym in cfg.universe:
        if sym in exclude:
            continue
        s = momentum_score(closes.get(sym) or [], cfg.lookbacks)
        if s is not None:
            scores[sym] = s
    if not scores:
        return {cfg.cash_symbol: 1.0}
    best = sorted(scores, key=scores.get, reverse=True)[: cfg.top_n]
    slot = 1.0 / cfg.top_n
    weights: dict[str, float] = {}
    for sym in best:
        key = sym if above_sma(closes[sym], cfg.sma_period) else cfg.cash_symbol
        weights[key] = weights.get(key, 0.0) + slot
    if len(best) < cfg.top_n:   # fewer eligible names than slots → rest in cash
        weights[cfg.cash_symbol] = weights.get(cfg.cash_symbol, 0.0) + slot * (cfg.top_n - len(best))
    return weights
