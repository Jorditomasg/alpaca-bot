import json
from pathlib import Path

_DATA = Path("data")
_DATA.mkdir(exist_ok=True)
STATE_FILE = _DATA / "rotation_state.json"


def load() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_rebalance_week": None, "last_weights": {}, "last_orders": [], "rebalances": 0}


def save(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
