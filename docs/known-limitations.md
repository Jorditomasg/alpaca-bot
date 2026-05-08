# Known Limitations

## SOFI Earnings Caveat

SOFI reports earnings quarterly (typically February, April/May, July/August, October).
Around earnings dates, implied volatility spikes dramatically, which can cause:

1. The spread to blow through the long strike and reach max loss.
2. Option bid-ask spreads to widen, making the score threshold unachievable.

**Current behavior**: The engine has NO automatic earnings-date filter. It will
attempt to open a new spread even during the earnings window if buying power
and scoring conditions are met.

**Operator action required**: Manually halt the wheel strategy before SOFI earnings
and resume after the IV crush settles (typically 1-2 days post-announcement).

To halt: stop the scheduler or set `WHEEL_STRATEGY_TYPE=csp` (which will not open
new CSP positions if no suitable contract is found, but will still run the cycle).
The cleanest halt is to simply stop the container and restart it after earnings.

**v2 roadmap**: Automated earnings filter using a financial calendar API.
Ticket placeholder: `#wheel-v2-earnings-filter`

---

## Stale Option Quotes Outside Regular Trading Hours

Alpaca paper option quotes can be stale (hours old) after market close. The
`spread_mid_price` profit-take check in `wheel/monitor.py` may fire on misleading
prices if called outside market hours.

**Mitigation**: `scheduler.wheel_task` gates on `market_hours.is_market_open()`
before calling the engine. The monitor inherits this gate.

---

## Multi-Leg Order Atomicity

Alpaca executes multi-leg (mleg) orders atomically: both legs fill together or
neither does. This change relies on that guarantee. If a future Alpaca SDK update
breaks atomic execution, a reconciliation pass would be needed to detect partial
fills.

---

## Score Threshold (0.30) May Be Too Aggressive

The credit/max-loss score threshold of 0.30 is fixed in v1. On low-IV days, SOFI
spreads may consistently score below 0.30 and the engine will stay IDLE all day.
Every rejected candidate is logged with its score, so this can be monitored from
production logs and tuned in a follow-up via `WHEEL_SCORE_THRESHOLD`.

---

## Items Resolved in Review Pass (2026-05-08)

The following issues identified during code review have been fixed and are no longer open:

- **Expiry P&L three-region accounting**: The engine now correctly handles spot between strikes (partial loss), spot above short strike (worthless), and spot below long strike (full max loss). The `total_premium` accounting reverses the optimistic credit before applying the realized P&L on losing closes.
- **Capital guard blocking spread close**: The guard now runs only in the `IDLE` branch. A `SPREAD_OPEN` state with insufficient buying power will still execute profit-take, expiry, and max-loss close paths normally.
- **Hardcoded 50% profit target in monitor**: `wheel/monitor.py` now reads `cfg.profit_target_pct` from `WheelConfig`. Configurable via `WHEEL_PROFIT_TARGET_PCT`.
- **Non-atomic state writes**: `wheel/state.py:save()` now writes to a temp file in the same directory as `STATE_FILE` and uses `os.replace()` for atomic rename.
- **One-sided quote acceptance**: `wheel/spreads.py:_mid()` now rejects a contract if EITHER bid OR ask is zero (previously required BOTH to be zero).
- **Symbol flip on non-IDLE state**: `wheel/state.py:load()` now only updates the symbol from `WHEEL_SYMBOL` env when `stage == "IDLE"`. Non-IDLE stages preserve the existing symbol and log a warning.
- **Wider-than-configured spread fallback**: `wheel/spreads.py` fallback long-leg selection now caps candidates at `width <= cfg.spread_width` and picks the widest qualifying leg. Spreads wider than configured are never opened.
- **State mutation before order confirmation**: `wheel/engine.py:_open_spread()` now calls `submit_order()` before mutating any state fields. A failed order leaves state as `IDLE`.
