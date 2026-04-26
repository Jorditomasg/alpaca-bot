from dataclasses import dataclass


@dataclass
class Action:
    type: str   # "buy" | "sell"
    qty: int
    reason: str


def evaluate(price: float, state: dict) -> list[Action]:
    actions: list[Action] = []

    # 1. Update high watermark
    if price > state["high_watermark"]:
        state["high_watermark"] = price

    # 2. Trailing stop: activates once price rises 10% above entry
    if price >= state["entry_price"] * 1.10:
        state["trailing_active"] = True
        new_floor = round(price * 0.95, 2)
        if new_floor > state["floor"]:
            print(f"[STRATEGY] Floor raised ${state['floor']:.2f} → ${new_floor:.2f}")
            state["floor"] = new_floor

    # 3. Stop loss: price hit or dropped below floor
    if price <= state["floor"]:
        actions.append(Action(
            type="sell",
            qty=state["position_qty"],
            reason=f"Floor breached — price=${price:.2f} floor=${state['floor']:.2f}",
        ))
        return actions  # skip ladder checks, position is being closed

    # Ladder buys — pyramid: more shares at deeper discounts
    # -15%: cautious re-entry after stop loss
    # -22%: increasing conviction
    # -30%: significant dip, more aggressive
    # -40%: crash territory, maximum conviction
    LADDERS = [
        ("ladder_15_done", 0.85, 10, "Ladder -15%"),
        ("ladder_22_done", 0.78, 20, "Ladder -22%"),
        ("ladder_30_done", 0.70, 30, "Ladder -30%"),
        ("ladder_40_done", 0.60, 50, "Ladder -40%"),
    ]

    for key, threshold, qty, label in LADDERS:
        if not state[key] and price <= state["entry_price"] * threshold:
            actions.append(Action(
                type="buy",
                qty=qty,
                reason=f"{label} — price=${price:.2f}",
            ))
            state[key] = True

    return actions
