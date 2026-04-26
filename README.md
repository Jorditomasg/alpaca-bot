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

### Wheel Strategy (TSLA)
Income generation via options during market hours:
- **Stage 1 — Sell Put:** ~10% OTM, 2–4 weeks out. Collect premium. Repeat if expires worthless.
- **Stage 2 — Sell Call:** Once assigned, sell covered call ~10% above cost basis. Repeat if expires worthless.
- Early close at 50% profit — buy to close and sell a new contract immediately
- Never sells a put without sufficient buying power
- Never sells a call below cost basis
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
  web/             — FastAPI dashboard (http://localhost:8080)
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
open http://localhost:8080
```

## Environment Variables

| Variable | Description |
|---|---|
| `ALPACA_API_KEY` | Alpaca API key |
| `ALPACA_SECRET_KEY` | Alpaca secret key |
| `ALPACA_BASE_URL` | `https://paper-api.alpaca.markets/v2` for paper trading |

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

Live status at `http://YOUR_SERVER_IP:8080` — auto-refreshes every 30 seconds.

Shows current state of all three strategies: positions, floors, premiums collected, and active contracts.
