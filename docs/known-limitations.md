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

---

## Open after the 2026-10-02 review

- **Wheel has no exit before expiry and no stop-loss.** On expiry day the first
  cycle (09:30 ET) books P&L from the opening spot as if cash-settled and resets
  to IDLE while both legs are still open at the broker. SOFI options are
  **physically settled**: an ITM short leg means assignment of 100 shares
  (~$1,550 on a ~$1,045 account). Fix = close at N DTE / on a loss threshold and
  only go IDLE once the broker shows no option positions — a trading-logic
  change, so it needs the §1 backtest gate first.
- **Copy and trailing can hold the same ticker, and both close with
  `close_position(symbol)`**, which liquidates the whole account position —
  including the other strategy's shares. Copy tracks notional, not quantity, so
  selling "only its share" needs per-position quantity tracking first.
- **State files written non-atomically by trailing/copy** while another thread
  reads them; `wheel_task` calls Alpaca synchronously inside the event loop.

## Items Resolved in Review Pass (2026-10-02)

- **Spread opens sent the credit with the WRONG SIGN.** Alpaca prices mleg
  orders as a net amount — positive = debit, negative = credit — so `+0.27`
  meant "willing to pay up to $0.27" and every open filled the same second at
  whatever credit the market gave (08-17 limit 0.36 → filled −0.20; 09-24 0.27 →
  −0.22). `build_open_order` now sends `-abs(credit)`.
- **Open fills were booked at the limit, not the fill**: `filled_avg_price` is
  negative for a credit and the `> 0` guard skipped it, overstating
  `net_credit`/`realized_pnl` (~$16 per cycle). Now `abs()` of the fill.
  `wheel_state.json` corrected by hand from the order history: realized −59.00
  (was −44.50), open credit 22.00 (was 26.50).
- **Profit-take priced at `short_bid − long_ask`**, documented as conservative
  but actually the most optimistic price (below mid by both half-spreads): 7 of
  9 close orders 08-20 → 09-25 expired unfilled. Now the mid of both legs, and a
  one-sided short quote no longer fakes a near-zero close cost.
- **Capitol Trades scraper parsed every date as "" and every amount as 0** on the
  live site (`22 Sept 2026`, `13:02 Today`, `1K–15K` with an en dash). The copier
  dropped every buy and every politician scored the same 0.450, so "following"
  just meant "most rows scraped". Regex fixed; regression fixture from the live
  page in `tests/fixtures/capitoltrades_page1_20261002.html`.
- **Trailing entry fell back to a hardcoded TSLA** when the scrape returned
  nothing (fired 2026-10-01: 30 % of buying power on no signal). It now skips the
  entry and retries.
- **A failed copy close dropped the position from local state** anyway, leaving
  unwatched shares at the broker. Now kept and retried; "position does not
  exist" is treated as closed.
