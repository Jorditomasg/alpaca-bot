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

# New-position size as % of account equity. 5% mirrors the validated backtest
# sweep configuration (notional 5000 on 100000 starting cash). Sizing relative
# to equity (not a fixed dollar notional) lets winners compound the base.
NOTIONAL_PCT          = _f("COPY_NOTIONAL_PCT", 5.0)

# Concentration controls (validated 2018-2020 sweep, see PROFITABILITY note in
# the commit). A fixed notional left capital idle AND let a hyperactive
# politician over-concentrate the book; these two caps are what drove the
# drawdown back under the -10% tolerance while lifting Sharpe.
#
# Max simultaneous open positions. The binding risk control: capping the book
# at 8 names took Perdue's max drawdown from -11.0% to -9.5% and ~2.6x'd Sharpe.
MAX_POSITIONS         = _i("COPY_MAX_POSITIONS", 8)

# Portfolio-level deployment ceiling as % of equity — keep dry powder so a
# market-wide gap down (COVID-style) cannot catch the book fully invested.
MAX_INVESTED_PCT      = _f("COPY_MAX_INVESTED_PCT", 80.0)

# Capitol Trades pages to scrape per poll. Page 0 alone (~12 rows) misses
# filings — including the followed politician's sells — on busy filing days.
SCRAPE_PAGES          = _i("COPY_SCRAPE_PAGES", 3)
