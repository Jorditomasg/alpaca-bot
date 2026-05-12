"""Wheel strategy state persistence.

State file: data/wheel_state.json

Schema after migration:
  strategy_type          : "csp" | "bull_put_spread"
  stage                  : "IDLE" | "PUT_OPEN" | "ASSIGNED" | "CALL_OPEN" (csp)
                           "IDLE" | "SPREAD_OPEN" (bull_put_spread)
  symbol                 : underlying ticker (from config)
  cycles                 : completed cycles counter
  total_premium          : all-time premium collected ($)
  premium_received       : premium for the currently open contract ($)

  -- CSP legs (null in spread mode) --
  contract_symbol        : active single-leg option symbol
  contract_strike        : strike price
  contract_expiry        : expiry date string
  cost_basis             : per-share cost after premiums (ASSIGNED stage)
  shares_owned           : number of shares held

  -- Spread legs (null in csp mode) --
  short_symbol           : short leg option symbol
  short_strike           : short leg strike price
  long_symbol            : long leg option symbol
  long_strike            : long leg strike price
  net_credit             : net credit received per spread ($)
  max_loss               : maximum possible loss per spread ($)
  spread_width           : actual width between strikes ($)
  contract_expiry        : shared expiry date (same field as csp)

  -- Capital guard --
  last_logged_insufficient_at : (rounded_bp, cycles) tuple or null; one-shot log latch
"""
import json
import os
from pathlib import Path
from wheel.config import get_config

_DATA = Path("data")
_DATA.mkdir(exist_ok=True)
STATE_FILE = _DATA / "wheel_state.json"


def load() -> dict:
    cfg = get_config()
    if STATE_FILE.exists():
        s = json.loads(STATE_FILE.read_text())
        # Backward-compat migration: old files have no strategy_type.
        # In-flight cycles (stage != IDLE) must preserve csp — there is a real
        # contract open and we cannot retroactively reinterpret it as a spread.
        # IDLE legacy state has nothing in flight, so respect cfg.strategy_type
        # instead of stranding users on csp when their capital fits a spread.
        if "strategy_type" not in s:
            if s.get("stage", "IDLE") == "IDLE":
                s["strategy_type"] = cfg.strategy_type
                print(
                    f"[WHEEL] Legacy state detected (IDLE) → strategy_type adopted from "
                    f"config: {cfg.strategy_type!r}."
                )
            else:
                s["strategy_type"] = "csp"  # preserve in-flight CSP cycle
                print(
                    "[WHEEL] Legacy state detected (in-flight) → strategy_type "
                    "preserved as 'csp'. Wait for IDLE before flipping strategy."
                )
        # Backfill spread fields absent in legacy CSP state files
        s.setdefault("short_symbol", None)
        s.setdefault("short_strike", None)
        s.setdefault("long_symbol", None)
        s.setdefault("long_strike", None)
        s.setdefault("net_credit", 0.0)
        s.setdefault("max_loss", 0.0)
        s.setdefault("spread_width", cfg.spread_width)
        s.setdefault("last_logged_insufficient_at", None)
        s.setdefault("realized_pnl", 0.0)
        # Ensure symbol comes from config (removes TSLA hardcode) for fresh files
        if "symbol" not in s:
            s["symbol"] = cfg.symbol

        # Symbol migration: explicit env override may flip symbol only when IDLE
        env_symbol = os.environ.get("WHEEL_SYMBOL")
        if env_symbol is not None:
            existing_symbol = s.get("symbol")
            stage = s.get("stage", "IDLE")
            if stage == "IDLE" and existing_symbol != env_symbol:
                print(
                    f"[WHEEL] Symbol overridden: {existing_symbol!r} → {env_symbol!r} "
                    f"(state is IDLE — safe to flip)"
                )
                s["symbol"] = env_symbol
            elif stage != "IDLE" and existing_symbol != env_symbol:
                print(
                    f"[WHEEL] WARNING: WHEEL_SYMBOL={env_symbol!r} differs from in-flight "
                    f"symbol={existing_symbol!r} (stage={stage}). "
                    f"Operator must wait until IDLE before flipping."
                )
                # Preserve existing symbol — do not overwrite

        return s

    # Fresh state uses the configured strategy and symbol
    return {
        "strategy_type": cfg.strategy_type,
        "stage": "IDLE",
        "symbol": cfg.symbol,
        "cycles": 0,
        "total_premium": 0.0,
        "premium_received": 0.0,
        # CSP legs
        "contract_symbol": None,
        "contract_strike": None,
        "contract_expiry": None,
        "cost_basis": None,
        "shares_owned": 0,
        # Spread legs
        "short_symbol": None,
        "short_strike": None,
        "long_symbol": None,
        "long_strike": None,
        "net_credit": 0.0,
        "max_loss": 0.0,
        "spread_width": cfg.spread_width,
        # Capital guard
        "last_logged_insufficient_at": None,
        # Lifetime realized P&L accumulator (persists across cycles)
        "realized_pnl": 0.0,
    }


def save(state: dict) -> None:
    """Write state atomically via a temp file + os.replace.

    A crash between write and replace leaves either the previous valid file
    or the new valid file on disk — never a truncated/empty file.
    The temp file is created in the same directory as STATE_FILE so that
    os.replace (which uses rename(2)) works without cross-device issues.
    """
    import tempfile
    target = Path(STATE_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".wheel_state_", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2, default=str)
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
