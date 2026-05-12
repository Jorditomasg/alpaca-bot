from dataclasses import dataclass

# Floor moves on every upward tick (tight SL), but the [STRATEGY] Floor raised
# line only prints when the floor crosses this fraction above the last LOGGED
# floor. Decouples log noise from stop-loss tightness.
FLOOR_LOG_STEP_PCT = 0.01

# Default trailing distance as a fraction of high watermark, used when no ATR
# is cached in state. ATR-based trailing (when available) overrides this.
DEFAULT_TRAIL_PCT = 0.05


@dataclass
class Action:
    type: str   # "buy" | "sell"
    qty: float = None
    notional: float = None
    reason: str = ""


def _compute_floor(state: dict) -> float:
    """Return the trailing floor based on the high watermark.

    Prefers ATR-based stop (high_watermark - k*ATR) when state has a fresh
    `atr` value; falls back to fixed-percentage trail otherwise.
    """
    hwm = state["high_watermark"]
    atr = state.get("atr")
    atr_k = state.get("atr_multiplier", 2.5)
    if atr and atr > 0:
        return round(hwm - atr_k * atr, 2)
    return round(hwm * (1.0 - DEFAULT_TRAIL_PCT), 2)


def evaluate(price: float, state: dict) -> list[Action]:
    actions: list[Action] = []

    # 1. Update high watermark
    if price > state["high_watermark"]:
        state["high_watermark"] = price

    # 2. Trailing stop: activates once price rises 10% above entry.
    # Compare via integer cents to dodge FP precision (400 * 1.10 == 440.000...006).
    if round(price * 100) >= round(state["entry_price"] * 110):
        state["trailing_active"] = True

        new_floor = _compute_floor(state)
        if new_floor > state["floor"]:
            old_floor = state["floor"]
            state["floor"] = new_floor  # SL stays tight on every tick

            # Log only when the floor crosses a meaningful step above the last
            # logged value — prevents cent-by-cent log spam.
            last_logged = state.get("last_logged_floor", old_floor)
            if new_floor >= last_logged + (last_logged * FLOOR_LOG_STEP_PCT):
                print(f"[STRATEGY] Floor raised ${last_logged:.2f} → ${new_floor:.2f}")
                state["last_logged_floor"] = new_floor

    # 3. Stop loss: price hit or dropped below floor
    if price <= state["floor"]:
        actions.append(Action(
            type="sell",
            qty=state["position_qty"],
            reason=f"Floor breached — price=${price:.2f} floor=${state['floor']:.2f}",
        ))
        return actions  # skip ladder checks, position is being closed

    # Ladder buys — pyramid: more capital at deeper discounts
    # -15%: $10 entry
    # -22%: $20 conviction
    # -30%: $30 dip
    # -40%: $50 aggressive
    LADDERS = [
        ("ladder_15_done", 0.85, 10.0, "Ladder -15%"),
        ("ladder_22_done", 0.78, 20.0, "Ladder -22%"),
        ("ladder_30_done", 0.70, 30.0, "Ladder -30%"),
        ("ladder_40_done", 0.60, 50.0, "Ladder -40%"),
    ]

    for key, threshold, amount, label in LADDERS:
        if not state[key] and price <= state["entry_price"] * threshold:
            actions.append(Action(
                type="buy",
                notional=amount,
                reason=f"{label} — price=${price:.2f}",
            ))
            state[key] = True

    return actions
