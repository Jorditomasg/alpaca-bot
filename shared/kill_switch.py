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

Why a breach must be CONFIRMED (2026-07-30 incident):
    A single phantom equity read of $607.80 latched the halt on the live paper
    account and killed the wheel strategy for days. Alpaca's own portfolio
    history showed equity never left the $1000–$1084 band over that period, so
    the reading was never real — most likely a partial account response during
    the DNS/websocket failure storm in the same logs. One bad sample must not
    be able to stop the bot, so a breach now has to hold for
    `KILL_SWITCH_CONFIRMATIONS` consecutive reads.

Why the halt RE-ARMS:
    A halt that can only be cleared by deleting a file on the host is a fuse,
    not a circuit breaker: whatever trips it — real drawdown or bad data —
    silently retires the strategy until someone notices. The halt now clears
    once drawdown recovers to `KILL_SWITCH_RECOVERY_FRACTION` of the limit,
    and `halt_count` keeps the audit trail of how often it fired.
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
DEFAULT_CONFIRMATIONS = 3        # consecutive breaching reads before halting
DEFAULT_RECOVERY_FRACTION = 0.5  # re-arm once DD is back under 50% of the limit

_NEW_FIELDS = {"breach_streak": 0, "halt_count": 0, "recovered_at": None}


def _max_dd_pct() -> float:
    return float(os.getenv("MAX_DRAWDOWN_PCT", str(DEFAULT_MAX_DRAWDOWN_PCT)))


def _confirmations() -> int:
    return max(1, int(os.getenv("KILL_SWITCH_CONFIRMATIONS", str(DEFAULT_CONFIRMATIONS))))


def _recovery_fraction() -> float:
    return float(
        os.getenv("KILL_SWITCH_RECOVERY_FRACTION", str(DEFAULT_RECOVERY_FRACTION))
    )


def load() -> dict:
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        # Backfill fields added after this file was first written, so an
        # existing halt survives the upgrade instead of KeyError-ing.
        for key, default in _NEW_FIELDS.items():
            state.setdefault(key, default)
        return state
    return {
        "peak_equity": None,
        "halted": False,
        "halted_at": None,
        "halted_equity": None,
        "halt_reason": None,
        **_NEW_FIELDS,
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
    for key, default in _NEW_FIELDS.items():
        state.setdefault(key, default)

    if current_equity <= 0:
        # Equity feed glitch; do not trip on bad data.
        return state

    peak = state.get("peak_equity")
    if peak is None or current_equity > peak:
        state["peak_equity"] = current_equity
        peak = current_equity

    dd = (peak - current_equity) / peak if peak else 0.0
    max_dd = _max_dd_pct()

    if state.get("halted"):
        # Re-arm once the drawdown has genuinely recovered — not the moment it
        # ticks back under the limit, which would flap around the threshold.
        if dd <= max_dd * _recovery_fraction():
            state["halted"] = False
            state["halted_at"] = None
            state["halted_equity"] = None
            state["halt_reason"] = None
            state["breach_streak"] = 0
            state["recovered_at"] = current_equity
        return state

    if dd < max_dd:
        state["breach_streak"] = 0
        return state

    # Breaching — but require the breach to hold before acting on it.
    state["breach_streak"] = state.get("breach_streak", 0) + 1
    confirmations = _confirmations()
    if state["breach_streak"] < confirmations:
        return state

    state["halted"] = True
    state["halted_at"] = current_equity
    state["halted_equity"] = current_equity
    state["halt_count"] = state.get("halt_count", 0) + 1
    state["halt_reason"] = (
        f"drawdown={dd:.1%} >= max={max_dd:.1%} "
        f"(peak=${peak:.2f}, equity=${current_equity:.2f}) "
        f"confirmed over {confirmations} consecutive reads"
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
