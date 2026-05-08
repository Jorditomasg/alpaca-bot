# Alpaca Bot

Automated trading bot for Alpaca paper trading. Three independent strategies running concurrently, with a real-time web dashboard.

## Strategies

### Trailing Stop (TSLA)
Buys 20 shares at market price and manages a dynamic floor:
- Stop loss at -10% from entry
- Trailing stop activates at +10% gain — floor moves up to 5% below peak, never down
- Ladder buys on dips: -15% → 10 shares, -22% → 20, -30% → 30, -40% → 50

### Copy Trader
Follows the top-performing US politician based on STOCK Act disclosures (Capitol Trades):
- Scores politicians by win rate (40%), recency (35%), and trade volume (25%)
- Re-scores every 24h, fetches new trades every 4h
- Allocates $100 total across all active copied positions
- Options trades are translated to their underlying stock

### Wheel Strategy
Income generation via options during market hours. Two modes available:

**Bull Put Spread mode (default):**
- Sells a credit spread: short put ~10% OTM + long put 2 strikes below
- Defined risk: max loss capped at spread width × 100
- Capital requirement: $400 minimum (2× spread width × 100)
- Early close at 50% profit; full credit kept if expires worthless
- No stock assignment possible — `IDLE → SPREAD_OPEN → IDLE` only

**CSP mode (legacy):**
- **Stage 1 — Sell Put:** ~10% OTM, 2–4 weeks out. Collect premium. Repeat if expires worthless.
- **Stage 2 — Sell Call:** Once assigned, sell covered call ~10% above cost basis. Repeat if expires worthless.
- Enable with `WHEEL_STRATEGY_TYPE=csp`

Both modes:
- Capital guard: skips cycle if buying power is below threshold (logs once, then silent)
- Early close at 50% profit
- Daily summary at market close

## Architecture

```
alpaca-bot/
  main.py          — entry point, starts all systems
  scheduler.py     — async orchestrator (trailing, copy, wheel)
  shared/          — Alpaca client, market hours, order execution
  trailing/        — trailing stop strategy + WebSocket stream
  copy/            — Capitol Trades scraper, scorer, portfolio manager
  wheel/           — options engine, monitor, daily summary
  web/             — FastAPI dashboard (http://localhost:7080)
  data/            — runtime state (gitignored, persisted via Docker volume)
```

## Requirements

- Python 3.12+
- Docker + Docker Compose
- Alpaca paper trading account

## Setup

```bash
# 1. Clone
git clone https://github.com/TU_USUARIO/alpaca-bot.git
cd alpaca-bot

# 2. Create .env from template
cp .env.example .env
# Edit .env with your Alpaca credentials

# 3. Run
docker compose up -d --build

# 4. Dashboard
open http://localhost:7080
```

## Environment Variables

| Variable | Description |
|---|---|
| `ALPACA_API_KEY` | Alpaca API key |
| `ALPACA_SECRET_KEY` | Alpaca secret key |
| `ALPACA_BASE_URL` | `https://paper-api.alpaca.markets/v2` for paper trading |

### Wheel Strategy Variables

| Variable | Type | Default | Description |
|---|---|---|---|
| `WHEEL_STRATEGY_TYPE` | string | `bull_put_spread` | `bull_put_spread` or `csp` |
| `WHEEL_SYMBOL` | string | `SOFI` | Underlying ticker for the wheel |
| `WHEEL_SPREAD_WIDTH` | float | `2` | Dollar width between short and long strike |
| `WHEEL_MIN_BUYING_POWER` | float | `width × 100 × 2` | Capital guard floor (default $400) |
| `WHEEL_TARGET_DTE_MIN` | int | `14` | Minimum days-to-expiry for contract selection |
| `WHEEL_TARGET_DTE_MAX` | int | `28` | Maximum days-to-expiry for contract selection |
| `WHEEL_PROFIT_TARGET_PCT` | float | `50` | Close position at this % of credit received |
| `WHEEL_TARGET_OTM_PCT` | float | `0.10` | Short strike distance from spot (10% = 1 strike OTM) |
| `WHEEL_SCORE_THRESHOLD` | float | `0.30` | Min credit/max-loss ratio to accept a spread |

## Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all unit + replay tests (integration skipped by default)
pytest tests/

# Run integration tests (requires paper API keys)
pytest -m integration

# Capture a live SOFI option chain fixture (run on a trading day)
python -m wheel.tools.capture_chain SOFI
```

## Deployment

Pushes to `main` automatically deploy to your server via GitHub Actions.

Required GitHub Secrets:

| Secret | Description |
|---|---|
| `SERVER_HOST` | Server IP or domain |
| `SERVER_USER` | SSH username |
| `SERVER_SSH_KEY` | Private SSH key |
| `SERVER_PORT` | SSH port (usually `22`) |

See [setup guide](#setup) for full server installation steps.

## Dashboard

Live status at `http://YOUR_SERVER_IP:7080` — auto-refreshes every 30 seconds.

Shows current state of all three strategies: positions, floors, premiums collected, and active contracts.
