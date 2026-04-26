import json
from pathlib import Path
from datetime import datetime

_DATA = Path("data")
_DATA.mkdir(exist_ok=True)
STATE_FILE = _DATA / "copy_state.json"


def load() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {
        "following": None,
        "last_scored": None,
        "seen_trade_ids": [],
        "positions": {},
    }


def save(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
