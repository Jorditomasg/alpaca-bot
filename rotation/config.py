"""Rotation configuration — env-driven so it can be tuned/disabled without a rebuild."""
import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class RotationConfig:
    # Diversified multi-asset universe: US large/small cap, tech, intl dev/EM,
    # long/mid Treasuries, gold, commodities, REITs. Validated 2007→2026.
    universe: tuple[str, ...] = ("SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD", "DBC", "VNQ")
    top_n: int = 3
    # Momentum = mean of the 1/3/6/12-month total returns (in trading days).
    lookbacks: tuple[int, ...] = (21, 63, 126, 252)
    # A slot whose ETF trades below its SMA goes to the cash ETF instead.
    sma_period: int = 200
    cash_symbol: str = "BIL"
    # Share of account equity the sleeve may hold. 0.5 keeps the sleeve's
    # historical worst drawdown (~-20 %) at ~-10 % of the account (§1 tolerance).
    alloc_pct: float = 0.5
    # Cash (as share of equity) never spent by the rotation, so trailing's
    # next entry (30 % of buying power) and the others keep their room (§5).
    reserve_pct: float = 0.30
    min_trade: float = 5.0
    # Rebalance a held name only when it is off target by more than this
    # fraction of its target value (avoids weekly micro-orders).
    drift_tol: float = 0.10
    enabled: bool = False


def load() -> RotationConfig:
    return RotationConfig(
        alloc_pct=float(os.getenv("ROTATION_ALLOC_PCT", "0.5")),
        reserve_pct=float(os.getenv("ROTATION_RESERVE_PCT", "0.30")),
        top_n=int(os.getenv("ROTATION_TOP_N", "3")),
        enabled=_env_bool("ROTATION_ENABLED", False),
    )
