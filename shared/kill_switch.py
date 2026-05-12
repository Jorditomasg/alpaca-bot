"""Global drawdown kill switch.

Tracks the high watermark of account equity since first activation. When current
equity drops more than `MAX_DRAWDOWN_PCT` below the high watermark, the bot is
prohibited from opening NEW positions — exits remain unblocked so existing risk
can be closed out.

State persists in data/kill_switch.json. Designed to be queried by every
new-position code path (wheel _open_spread, _open_put, _open_call,
trailing initial-entry, trailing ladder buys).

Why high-watermark drawdown (not starting-equity drawdown):
    Starting-equity DD treats $100 → $200 → $180 as 80% UP. High-watermark DD
    treats it as 10% DOWN from peak. The latter is the meaningful drawdown
    measure that tells you when something has actually broken in your strategy.
"""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path

_DATA = Path("data")
_DATA.mkdir(exist_ok=True)
STATE_FILE = _DATA / "kill_switch.json"

DEFAULT_MAX_DRAWDOWN_PCT = 0.20  # 20% from peak triggers halt


def _max_dd_pct() -> float:
    return float(os.getenv("MAX_DRAWDOWN_PCT", str(DEFAULT_MAX_DRAWDOWN_PCT)))


def load() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {
        "peak_equity": None,
        "halted": False,
        "halted_at": None,
        "halted_equity": None,
        "halt_reason": None,
    }


def save(state: dict) -> None:
    target = Path(STATE_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".kill_switch_", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def update(current_equity: float, state: dict | None = None) -> dict:
    """Update the high watermark and decide if the kill switch should trip.

    Pure function over state — caller persists via save().
    Returns the (possibly mutated) state.
    """
    if state is None:
        state = load()

    if current_equity <= 0:
        # Equity feed glitch; do not trip on bad data.
        return state

    peak = state.get("peak_equity")
    if peak is None or current_equity > peak:
        state["peak_equity"] = current_equity
        peak = current_equity

    if state.get("halted"):
        # Once tripped, stays tripped until manually reset (delete the file).
        return state

    dd = (peak - current_equity) / peak if peak else 0.0
    max_dd = _max_dd_pct()
    if dd >= max_dd:
        state["halted"] = True
        state["halted_at"] = current_equity
        state["halted_equity"] = current_equity
        state["halt_reason"] = (
            f"drawdown={dd:.1%} >= max={max_dd:.1%} "
            f"(peak=${peak:.2f}, equity=${current_equity:.2f})"
        )

    return state


def is_halted(state: dict | None = None) -> bool:
    """Return True if new positions must be blocked."""
    if state is None:
        state = load()
    return bool(state.get("halted"))


def reason(state: dict | None = None) -> str | None:
    if state is None:
        state = load()
    return state.get("halt_reason") if state.get("halted") else None
