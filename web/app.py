import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request

app = FastAPI()
templates = Jinja2Templates(directory="web/templates")


def _read(path: str) -> dict:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else {}


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/status")
async def status():
    trailing = _read("data/trailing_state.json")
    copy     = _read("data/copy_state.json")
    wheel    = _read("data/wheel_state.json")

    return {
        "trailing": {
            "symbol":           trailing.get("symbol", "TSLA"),
            "entry_price":      trailing.get("entry_price"),
            "floor":            trailing.get("floor"),
            "position_qty":     trailing.get("position_qty", 0),
            "trailing_active":  trailing.get("trailing_active", False),
            "high_watermark":   trailing.get("high_watermark"),
            "active":           bool(trailing),
        },
        "copy": {
            "following":     copy.get("following"),
            "positions":     copy.get("positions", {}),
            "total_capital": copy.get("total_capital", 100),
            "last_scored":   copy.get("last_scored"),
            "active":        bool(copy.get("following")),
        },
        "wheel": {
            "symbol":         wheel.get("symbol", "TSLA"),
            "stage":          wheel.get("stage", "IDLE"),
            "total_premium":  wheel.get("total_premium", 0),
            "cycles":         wheel.get("cycles", 0),
            "contract":       wheel.get("contract_symbol"),
            "strike":         wheel.get("contract_strike"),
            "expiry":         wheel.get("contract_expiry"),
            "shares_owned":   wheel.get("shares_owned", 0),
            "cost_basis":     wheel.get("cost_basis"),
            "active":         bool(wheel),
        },
    }
