import json
from pathlib import Path

STATE_FILE = Path("trailing_state.json")


def load() -> dict | None:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return None


def save(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def clear() -> None:
    if STATE_FILE.exists():
        STATE_FILE.unlink()
