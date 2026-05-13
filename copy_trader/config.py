"""Tunable parameters for the copy strategy.

Each is overridable via env var. Defaults match the values validated in the
2018-2020 backtest sweep (see backtest/runner.py results):
  - improved Sharpe across all politicians tested
  - 5-8x drawdown reduction vs baseline
  - return-positive on bad-stock-picker politicians (Perdue: -13% → +7%)
"""
import os


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# Filings older than this many days are considered stale signals.
PUB_FRESHNESS_DAYS    = _i("COPY_PUB_FRESHNESS_DAYS", 30)

# Politician trade dollar amount must be at least this much to copy.
# Filters out the $1k–$15k bucket (mid ≈ $8k) which is often noise.
MIN_AMOUNT            = _i("COPY_MIN_AMOUNT", 15000)

# Hard stop loss as % below cost basis.
STOP_LOSS_PCT         = _f("COPY_STOP_LOSS_PCT", 8.0)

# Trailing-stop arms once peak gain crosses this %.
TRAIL_ARM_PCT         = _f("COPY_TRAIL_ARM_PCT", 8.0)

# Once armed, exit if price falls back this % from high watermark.
TRAIL_GIVEBACK_PCT    = _f("COPY_TRAIL_GIVEBACK_PCT", 5.0)

# After this many days of holding, the political signal is considered decayed.
MAX_HOLDING_DAYS      = _i("COPY_MAX_HOLDING_DAYS", 180)
