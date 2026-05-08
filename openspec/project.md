# alpaca-bot — Project Context

Automated paper-trading bot running three concurrent strategies against Alpaca's paper API, with a FastAPI dashboard.

## Stack

- **Language**: Python 3.12
- **Runtime**: asyncio (single event loop, three long-running tasks)
- **Web**: FastAPI + uvicorn (dashboard on port 7080)
- **Trading**: `alpaca-py>=0.13.0` (sync TradingClient, StockHistoricalDataClient, OptionHistoricalDataClient)
- **HTTP**: `httpx` (Capitol Trades scraping)
- **Templating**: Jinja2 (dashboard)
- **Time**: `pytz` (America/New_York for market hours)
- **Config**: `python-dotenv` reading `.env` (ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)
- **Container**: `python:3.12-slim` via Docker / docker-compose; volume-mounted `./data:/app/data`
- **CI/CD**: GitHub Actions on push to `main` → SSH deploy to home server (no test step)

## Module Layout

```
alpaca-bot/
  main.py            entry point — starts FastAPI + 3 async tasks
  scheduler.py       async orchestrator (trailing_task, copy_task, wheel_task)
  shared/            Alpaca client factory, market_hours, trader (buy/sell/get_buying_power/get_latest_price)
  trailing/          trailing-stop strategy
    state.py         load/save/clear data/trailing_state.json
    strategy.py      pure evaluator returning Action[]
    stream.py        WebSocket price stream
  copy_trader/       Capitol Trades follower
    scraper.py       fetch_trades (sync httpx.Client)
    scorer.py        score_and_pick / get_consensus_ticker
    copier.py        new_trades_to_copy
    portfolio.py     execute_batch / _rebalance / close_position
    state.py         data/copy_state.json
  wheel/             options wheel strategy (TSLA)
    engine.py        IDLE → PUT_OPEN → ASSIGNED → CALL_OPEN state machine
    monitor.py       early-close at 50% profit
    options.py       contract selection helpers
    summary.py       daily summary at market close
    state.py         data/wheel_state.json
  web/               FastAPI dashboard
    app.py           GET / (template) and GET /api/status (reads JSON files)
    templates/       Jinja2 templates
    static/          assets
  data/              runtime state (gitignored, persisted via Docker volume)
```

## Architectural Conventions

1. **State**: each strategy owns a `state.py` with `load() -> dict` and `save(state: dict) -> None`, persisted as JSON under `data/`. No DB.
2. **Async boundary**: `alpaca-py` and `httpx.Client` are SYNCHRONOUS. From async tasks, ALWAYS call them via `loop.run_in_executor(None, fn)` to avoid blocking the event loop. See `scheduler.trailing_task` and `scheduler.copy_task` for the canonical pattern.
3. **Logs**: side-effect `print()` with bracketed tag prefixes — `[TRAILING]`, `[COPY]`, `[WHEEL]`, `[TRADER]`, `[PORTFOLIO]`, `[STRATEGY]`, `[PORTFOLIO]`. No structured logger.
4. **Error handling**: try/except around every Alpaca submit/fetch with print + continue. Never let one strategy crash another — the gather() in `main.py` would die.
5. **Module APIs**: prefer free functions over classes. `dataclasses` for value objects (e.g. `Action` in `trailing/strategy.py`).
6. **Market hours**: `shared.market_hours.is_market_open()` and `is_market_close()` use ET; weekends excluded.
7. **Money**: notional dollars (rounded to 2 decimals) preferred over share counts for fractional-friendly orders.

## Testing

NO test runner exists. No `pytest`, `tests/`, `pyproject.toml`, or `conftest.py`. Quality is validated by running `docker compose up -d --build` against the paper account and watching the dashboard plus container logs.

**Recommendation**: any SDD change that introduces non-trivial logic SHOULD also bootstrap pytest (add `pytest`, `pytest-asyncio` to `requirements.txt`, create `tests/`, add `pyproject.toml` with `[tool.pytest.ini_options]`). The pure functions in `trailing/strategy.py` and `copy_trader/scorer.py` are excellent first targets.

## Deployment

`.github/workflows/deploy.yml` SSHes into the server and runs `git pull && docker compose up -d --build && docker system prune -f`. Secrets: `SERVER_HOST`, `SERVER_USER`, `SERVER_SSH_KEY`, `SERVER_PORT`. NO test job blocks merges.

## Constraints

- Paper trading only — `alpaca_client.trading()` hard-codes `paper=True`.
- Single-instance: state is local JSON; running two containers concurrently against the same `data/` would corrupt state.
- `.env` is gitignored; `*.json` is gitignored (covers `data/*.json`).
