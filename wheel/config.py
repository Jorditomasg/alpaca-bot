"""Centralised wheel strategy configuration.

All knobs are read from environment variables once and cached. No imports
from wheel.* to avoid circular dependencies.

Usage:
    from wheel.config import get_config
    cfg = get_config()
"""
import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class WheelConfig:
    strategy_type: str     # "bull_put_spread" | "csp"
    symbol: str            # underlying ticker, e.g. "SOFI"
    spread_width: float    # dollars between short and long strike
    min_buying_power: float  # capital guard floor
    target_dte_min: int    # days to expiry, lower bound
    target_dte_max: int    # days to expiry, upper bound
    profit_target_pct: float  # e.g. 50.0 → close at 50% of credit received
    target_otm_pct: float  # 0..1; short strike = spot * (1 - otm_pct)
    score_threshold: float  # minimum credit/max-loss ratio to accept spread


@lru_cache(maxsize=1)
def get_config() -> WheelConfig:
    width = float(os.getenv("WHEEL_SPREAD_WIDTH", "2"))
    default_min_bp = width * 100 * 2
    return WheelConfig(
        strategy_type=os.getenv("WHEEL_STRATEGY_TYPE", "bull_put_spread"),
        symbol=os.getenv("WHEEL_SYMBOL", "SOFI"),
        spread_width=width,
        min_buying_power=float(os.getenv("WHEEL_MIN_BUYING_POWER", str(default_min_bp))),
        target_dte_min=int(os.getenv("WHEEL_TARGET_DTE_MIN", "14")),
        target_dte_max=int(os.getenv("WHEEL_TARGET_DTE_MAX", "28")),
        profit_target_pct=float(os.getenv("WHEEL_PROFIT_TARGET_PCT", "50")),
        target_otm_pct=float(os.getenv("WHEEL_TARGET_OTM_PCT", "0.10")),
        score_threshold=float(os.getenv("WHEEL_SCORE_THRESHOLD", "0.30")),
    )
