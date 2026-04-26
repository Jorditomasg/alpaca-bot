# TSLA Trailing Stop Strategy — Design Spec

**Date:** 2026-04-26
**Symbol:** TSLA (extensible to others)
**Account:** Alpaca Paper Trading

---

## 1. Overview

A continuous Python process that monitors TSLA price via Alpaca WebSocket, manages a trailing stop floor, executes ladder buys on dips, and persists state across restarts.

---

## 2. Architecture

```
Alpaca WebSocket (real-time TSLA price ticks)
        │
        ▼
    stream.py  ──── price ────▶  strategy.py
                                      │
                              ┌───────┴────────┐
                              │                │
                          state.py         trader.py
                        (state.json)    (Alpaca REST API)
                              │
                          main.py
                        (entry point)
```

### Module responsibilities

| Module | Does | Does NOT do |
|---|---|---|
| `stream.py` | Connects to WS, receives ticks, calls strategy | Know anything about orders |
| `strategy.py` | Evaluates rules, decides actions | Talk to Alpaca directly |
| `trader.py` | Places/cancels orders via REST | Know trading rules |
| `state.py` | Reads/writes state.json atomically | Evaluate anything |
| `main.py` | Starts, recovers state, orchestrates | Contain business logic |

---

## 3. State Schema

Persisted to `state.json`:

```json
{
  "symbol": "TSLA",
  "entry_price": 250.00,
  "position_qty": 10,
  "floor": 225.00,
  "trailing_active": false,
  "high_watermark": 250.00,
  "ladder_20_done": false,
  "ladder_30_done": false
}
```

---

## 4. Strategy Rules (per price tick)

Evaluated in this order:

1. **Update high watermark**
   `high_watermark = max(high_watermark, current_price)`

2. **Trailing stop activation** — if `current_price >= entry_price * 1.10`:
   - Set `trailing_active = true`
   - `new_floor = current_price * 0.95`
   - `floor = max(floor, new_floor)` — floor only moves up, never down

3. **Stop loss** — if `current_price <= floor`:
   - Place market sell for all shares
   - Delete state.json (clean slate for next trade)

4. **Ladder -20%** — if `current_price <= entry_price * 0.80` and not `ladder_20_done`:
   - Place market buy for 20 shares
   - Set `ladder_20_done = true`

5. **Ladder -30%** — if `current_price <= entry_price * 0.70` and not `ladder_30_done`:
   - Place market buy for 10 shares
   - Set `ladder_30_done = true`

### Known trade-off: stop loss vs ladder conflict

If price drops -10% (stop loss triggers), the position is closed before reaching -20%/-30% ladder levels. The ladder orders are intended for re-entry after the stop, not averaging down while holding. If the desired behavior changes, this rule ordering must be revisited.

---

## 5. Startup and Recovery

```
main.py starts
    │
    ├── state.json exists?
    │       YES → load state, verify open orders with Alpaca GET /orders
    │       NO  → place market buy 10 TSLA, write initial state
    │
    └── start stream.py → infinite tick loop
```

**Atomicity:** state is written to disk before placing any order. On restart, if state exists but the corresponding Alpaca order is missing, the order is re-placed.

---

## 6. Technical Stack

- `alpaca-py` — official Alpaca SDK (REST + WebSocket)
- `python-dotenv` — loads `.env` credentials
- No database — `state.json` is sufficient for a single symbol

WebSocket reconnection is handled automatically by `alpaca-py`.

---

## 7. File Structure

```
alpaca-bot/
  .env                  ← credentials (gitignored)
  state.json            ← runtime state (gitignored)
  main.py               ← entry point
  strategy.py           ← trading rules
  trader.py             ← Alpaca REST calls
  stream.py             ← WebSocket price feed
  state.py              ← state persistence
  requirements.txt
  docs/
    superpowers/
      specs/
        2026-04-26-tsla-trailing-stop-strategy-design.md
```
