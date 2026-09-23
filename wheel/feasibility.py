"""Detect a wheel configuration that can never open a trade.

`best_bull_put_spread` rejects a candidate whose `score` (credit / max_loss)
sits below `WHEEL_SCORE_THRESHOLD`, and that is the right behaviour for a
market that is simply paying too little today. It is the wrong behaviour, and
an invisible one, when the threshold is unreachable *by construction*.

Score falls monotonically as the short strike moves out of the money: a further
strike is less likely to be breached, so it pays less. `WHEEL_TARGET_OTM_PCT`
therefore caps the score the engine can ever observe, and
`_fetch_option_chain` narrows the strike window to that target — the engine
cannot even see the strikes that would qualify. Measured on the live SOFI chain
(2026-08-15, spot $18.29, $2 wide, 20-27 DTE):

    OTM  12.5%  score 0.03 - 0.06
    OTM   9.8%  score 0.08 - 0.09   <- the configured target
    OTM   7.1%  score 0.08 - 0.14
    OTM   4.3%  score 0.17 - 0.19
    OTM   1.6%  score 0.30 - 0.36   <- the configured threshold

With `target_otm_pct=0.10` and `score_threshold=0.30` the engine had rejected
every candidate since the account opened: `cycles: 0`, `total_premium: 0.0`.

This module keeps no opinion on which knob is wrong — that is a risk decision,
not a code one. It only guarantees the situation is reported instead of
scrolling past in a log nobody reads. The state it writes lives in the caller's
wheel state dict, so it survives restarts.
"""
from __future__ import annotations

import os

# Cycles of unbroken rejection before the config is called into question. The
# wheel runs every 15 min during market hours, so the default is ~1.5 sessions:
# long enough that a genuinely quiet stretch does not trip it.
DEFAULT_INFEASIBLE_AFTER = int(os.getenv("WHEEL_INFEASIBLE_AFTER_CYCLES", "40"))


def observe(
    state: dict,
    best_score: float | None,
    threshold: float,
    *,
    infeasible_after: int = DEFAULT_INFEASIBLE_AFTER,
) -> str | None:
    """Record one no-trade cycle; return a warning the first time it looks stuck.

    Args:
        state:        wheel state dict, mutated in place (JSON-serialisable).
        best_score:   best credit/max-loss seen this cycle, or None when no
                      spread was quotable at all.
        threshold:    the configured `score_threshold` it was measured against.
        infeasible_after: consecutive dry cycles before warning.

    Returns:
        A one-line warning the first cycle the streak is reached, else None.
        Callers should surface it once (log + notification), not per cycle.
    """
    if best_score is not None and best_score >= threshold:
        # A trade was possible — the config is demonstrably reachable.
        state["dry_cycles"] = 0
        state["best_score_seen"] = None
        state["infeasible_warned"] = False
        return None

    state["dry_cycles"] = int(state.get("dry_cycles", 0)) + 1
    seen = state.setdefault("best_score_seen", None)

    if best_score is not None:
        state["best_score_seen"] = best_score if seen is None else max(seen, best_score)

    if state["dry_cycles"] < infeasible_after or state.get("infeasible_warned"):
        return None

    state["infeasible_warned"] = True
    ceiling = state.get("best_score_seen")
    if ceiling is None:
        return (
            f"[WHEEL] {state['dry_cycles']} cycles with no quotable spread at all "
            f"— every candidate had a one-sided or missing quote. This is a data "
            f"problem, not a threshold one: check the symbol still has a liquid "
            f"option chain in the configured DTE window."
        )
    return (
        f"[WHEEL] {state['dry_cycles']} cycles without a single qualifying spread. "
        f"Best score reachable was {ceiling:.2f} against a threshold of "
        f"{threshold:.2f} — the strategy cannot fire as configured. "
        f"Score falls as the short strike moves further OTM, so either lower "
        f"WHEEL_SCORE_THRESHOLD toward the observed ceiling or lower "
        f"WHEEL_TARGET_OTM_PCT to sell closer to the money (more premium, "
        f"higher assignment risk)."
    )
