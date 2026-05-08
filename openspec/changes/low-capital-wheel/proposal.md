# Proposal: low-capital-wheel

## Why

The current wheel strategy is unusable on a $1,000 paper account: it is hardcoded to TSLA (~$385), where a single cash-secured put requires ~$34,600 in collateral, so the capital guard refuses every cycle and the strategy never trades. Defined-risk bull put spreads on a cheap, liquid underlying (SOFI) reduce the per-trade capital requirement to $200-$500, eliminate assignment risk, and unlock 8-12% expected monthly yield on the same $1,000 account. Because this change touches real money flow (multi-leg orders, P&L calculation, profit-take logic), we cannot ship it without an automated test suite — the codebase currently has zero tests, which is unacceptable for a strategy module. This proposal locks in the spread-aware engine, the SOFI default, the capital guard threshold, and the bootstrap of `pytest` as a single coherent change.

## What changes

- **New strategy type**: `bull_put_spread` becomes the default wheel strategy. The legacy CSP path is preserved behind a `strategy_type` config switch for users with larger accounts.
- **New default symbol**: `SOFI` replaces `TSLA` as the wheel default. The hardcode in `wheel/state.py:14` and the `TSLA` constant in `scheduler.py:29` are removed in favor of explicit configuration.
- **Spread state machine**: state flow simplifies to `IDLE → SPREAD_OPEN → IDLE`. The `ASSIGNED` and `CALL_OPEN` states are bypassed for spread mode (no stock delivery is possible).
- **Capital guard**: a minimum-buying-power check refuses to open a cycle when available capital is below `spread_width × 100 × 2`. The guard logs once on transition (not every tick) and skips cleanly.
- **Multi-leg order construction**: a new `wheel/spreads.py` module builds `OptionLegRequest` payloads with `OrderClass.MLEG` for the short put + long put pair.
- **50%-profit monitor**: the existing logic in `wheel/monitor.py` is generalized to operate on the net spread credit instead of a single-leg premium.
- **Test infrastructure**: `pytest`, `pytest-asyncio`, and `pytest-mock` are added to dev dependencies. Three test layers: unit (mocked clients), replay (JSON option-chain fixtures), and integration (`@pytest.mark.integration`, paper account, opt-in).
- **Fixture capture tooling**: a small operator script `wheel/tools/capture_chain.py` snapshots a live SOFI option chain to `tests/fixtures/` so replay tests can be regenerated when the chain shape changes.

## Out of scope

- Iron condors and other 4-leg structures (deferred to v2 once spread engine is proven).
- Poor Man's Covered Call (PMCC) or LEAPS-based strategies.
- Synthetic wheel (two-phase put spread + call spread mimicry of full assignment cycle).
- Automatic symbol selection / screening (the wheel will require explicit config; auto-screen is a v2 enhancement).
- Live-account upgrade flow (Alpaca Level 3 is auto-enabled on paper but requires a manual application for live; live deployment is a separate change).
- Migration of the existing `trailing` and `copy_trader` paths — they remain untouched.
- Backfilling tests for the legacy CSP path beyond what is needed to keep it from regressing.

## Decisions locked in this proposal

1. **Spread width: $2 default.** $2-wide spreads provide finer granularity, allow up to 5 concurrent contracts on $1,000, and produce smoother P&L than $5-wide. SOFI's chain has $0.50/$1 strike spacing so $2-wide spreads are always constructible at 10%-OTM. Width is configurable; $5 remains valid for higher-priced underlyings.
2. **Symbol selection: explicit config, default `SOFI`.** The wheel is a focused income strategy, not a screener — auto-selection adds an entire layer of failure modes (liquidity scoring, IV-rank ranking, earnings filters) that this change does not need. SOFI is liquid, sub-$15, and has a healthy options chain. Auto-screening becomes a v2 ticket once the spread engine is stable.
3. **Capital guard: `spread_width × 100 × 2` minimum (= $400 for the default width).** Below two contracts the strategy cannot diversify timing or strike, so a single bad fill consumes the whole opportunity. The guard logs once per transition into the under-capitalized state to avoid log spam.
4. **Strategy type config: `strategy_type: "bull_put_spread" | "csp"`.** Users with > $30K can flip back to classic CSP without a code change. The dispatch lives at the top of the engine; both paths share the symbol, monitor, and summary code.
5. **Fixture capture script: in scope.** Without captured chains, replay tests cannot exist, and replay tests are the only way to validate spread P&L behavior offline. The script is small (one async call to `OptionHistoricalDataClient` via `run_in_executor`, dump to JSON) and lives under `wheel/tools/` so it does not pollute production code paths.

## Impact

**Modified modules:**
- `wheel/state.py` — remove TSLA default, add spread-specific state fields (short/long contract symbols, net credit, max loss).
- `wheel/engine.py` — strategy dispatch on `strategy_type`, new `SPREAD_OPEN` transitions, capital guard with one-shot logging.
- `wheel/options.py` — strike window logic generalized to handle sub-$10 underlyings; helper to find the long-leg strike at `short_strike - width`.
- `wheel/monitor.py` — 50%-profit logic operates on net spread credit.
- `wheel/summary.py` — report spread credit, max loss, and current spread P&L instead of (or in addition to) single-leg fields.
- `scheduler.py` — drop the `TSLA` constant; symbol comes from config.

**New modules:**
- `wheel/spreads.py` — multi-leg order construction (`OptionLegRequest` + `OrderClass.MLEG`).
- `wheel/tools/capture_chain.py` — operator script for option-chain fixture capture.
- `tests/` — full test tree (unit, replay, integration markers, conftest, fixtures).

**New dev dependencies:**
- `pytest`, `pytest-asyncio`, `pytest-mock` (added to `pyproject.toml` or equivalent).

**Configuration:**
- New keys: `wheel.strategy_type`, `wheel.symbol`, `wheel.spread_width`, `wheel.min_buying_power_override` (optional).

**Untouched:** `trailing/*`, `copy_trader/*`, scraper, portfolio batch executor.

## Success criteria

1. The bot opens at least one bull put spread on SOFI on a paper account end-to-end (order accepted, fill confirmed, state persisted to `data/`).
2. The 50%-profit monitor closes that spread automatically when net P&L reaches 50% of the credit received.
3. Unit tests cover every state-machine transition (`IDLE → SPREAD_OPEN`, `SPREAD_OPEN → IDLE` via profit-take, `SPREAD_OPEN → IDLE` via expiry, capital-guard refusal) and all contract-selection edge cases.
4. At least one replay test runs against a captured SOFI option chain JSON fixture and asserts the expected spread is selected and priced.
5. The capital guard refuses cleanly with a single log line when buying power is below `spread_width × 100 × 2`, and does not spam on subsequent ticks.
6. The `trailing` and `copy_trader` execution paths remain bit-for-bit unchanged in behavior (verified by running the existing scheduler against them with the new wheel disabled).
7. `pytest` runs green from a clean checkout via a single documented command (`uv run pytest` or equivalent), with integration tests skipped by default.
