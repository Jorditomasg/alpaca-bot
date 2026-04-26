import json
from pathlib import Path

STATE_FILE = Path("wheel_state.json")


def load() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {
        "stage": "IDLE",          # IDLE | PUT_OPEN | ASSIGNED | CALL_OPEN
        "symbol": "TSLA",
        "contract_symbol": None,   # active option contract
        "contract_strike": None,
        "contract_expiry": None,
        "premium_received": 0.0,   # premium for current contract
        "total_premium": 0.0,      # all-time premium collected
        "cost_basis": None,        # per-share cost after premiums (ASSIGNED stage)
        "shares_owned": 0,
        "cycles": 0,
    }


def save(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
