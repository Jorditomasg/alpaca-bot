# Tasks: low-capital-wheel

## 1. Test infrastructure bootstrap (must come first)

- [x] 1.1 Create `pyproject.toml` with `[project]` metadata + `[project.optional-dependencies] dev = [pytest, pytest-asyncio, pytest-mock]`
- [x] 1.2 Add `[tool.pytest.ini_options]` block: `addopts = "-m 'not integration'"`, `markers = ["integration: runs against paper account (deselect with -m 'not integration')"]`, `asyncio_mode = "auto"`
- [x] 1.3 Create directory tree: `tests/unit/`, `tests/replay/`, `tests/integration/`, `tests/fixtures/option_chains/`
- [x] 1.4 Create `tests/conftest.py` with autouse fixture that calls `get_config.cache_clear()` before and after each test (env-leak guard)
- [x] 1.5 Add smoke `tests/unit/test_smoke.py` asserting `1 + 1 == 2` — verifies pytest wiring before any real code exists
- [x] 1.6 Document dev install path: add `pip install -e ".[dev]"` note to README (or requirements-dev.txt if pyproject.toml is blocked by existing setup)

---

## 2. Configuration layer

- [x] 2.1 Create `wheel/config.py` with frozen `WheelConfig` dataclass: `strategy_type`, `symbol`, `spread_width`, `min_buying_power`, `target_dte_min`, `target_dte_max`, `profit_target_pct`, `otm_pct`, `score_threshold`
- [x] 2.2 Implement `get_config() -> WheelConfig` with `@lru_cache(maxsize=None)` reading env vars (`WHEEL_STRATEGY_TYPE` default `"bull_put_spread"`, `WHEEL_SYMBOL` default `"SOFI"`, `WHEEL_SPREAD_WIDTH` default `2`, `WHEEL_MIN_BUYING_POWER` default `spread_width*100*2`, `WHEEL_TARGET_DTE_MIN` default `14`, `WHEEL_TARGET_DTE_MAX` default `28`, `WHEEL_PROFIT_TARGET_PCT` default `0.50`)
- [x] 2.3 Unit tests `tests/unit/test_config.py`: default values, env override for each var, `cache_clear()` between subtests

---

## 3. State schema migration

- [x] 3.1 Extend `wheel/state.py` schema constants / TypedDict with spread fields: `strategy_type`, `short_leg_symbol`, `long_leg_symbol`, `short_strike`, `long_strike`, `spread_width`, `net_credit`, `expiry`, `last_logged_insufficient_at`
- [x] 3.2 Add migration in `load()`: if `strategy_type` key absent → inject `"csp"` (preserves open CSP positions); if `strategy_type == "bull_put_spread"` and spread fields absent → inject `None` values
- [x] 3.3 Remove the `TSLA` hardcode from any symbol reference in `state.py`; symbol now always sourced from config
- [x] 3.4 Unit tests `tests/unit/test_state.py`: legacy-file migration → defaults to `"csp"`, fresh state → `"bull_put_spread"` (per config), all spread fields present and null in IDLE, round-trip JSON write/read

---

## 4. Spread selection module

- [x] 4.1 Create `wheel/spreads.py` with `best_bull_put_spread(symbol, current_price, chain, cfg: WheelConfig) -> SpreadCandidate | None`
- [x] 4.2 Implement strike selection: filter chain to puts within configured DTE range; short strike ~`(1 - otm_pct) * current_price`; long strike = `short_strike - spread_width`; fallback to closest-below long leg when exact width unavailable
- [x] 4.3 Implement scoring: `net_credit / max_loss >= score_threshold (0.30)`; log-and-return-None for candidates below threshold
- [x] 4.4 Implement multi-leg order construction: `LimitOrderRequest` with `OrderClass.MLEG`; two `OptionLegRequest` entries — `PositionIntent.SELL_TO_OPEN` (short) and `PositionIntent.BUY_TO_OPEN` (long); limit price = net credit (never market)
- [x] 4.5 Unit tests `tests/unit/test_spreads.py`: happy-path strike selection, score threshold rejection, missing-exact-width fallback, order-object shape validation (field presence, correct intents)

---

## 5. Engine refactor

- [x] 5.1 Refactor `wheel/engine.py:run_cycle()` into a dispatcher: read `state["strategy_type"]`, call `_run_csp_cycle()` (unchanged) or `_run_spread_cycle()` (new); CSP path MUST remain bit-for-bit identical to current behavior
- [x] 5.2 Implement `_run_spread_cycle()` IDLE → SPREAD_OPEN transition: capital guard check, call `best_bull_put_spread`, submit order, persist all spread fields to state on fill
- [x] 5.3 Implement SPREAD_OPEN → IDLE transitions in `_run_spread_cycle()`: (a) profit-take when spread mid ≤ 50% of net credit — submit closing mleg order, increment cycles; (b) expiry worthless — record full credit as realized profit, increment cycles; (c) max-loss at expiry — record `(spread_width * 100) - net_credit` as realized loss, increment cycles
- [x] 5.4 Capital guard: compute `rounded_bp = round(buying_power, -2)`; log warning only when `(rounded_bp, cycles)` bucket changes (latch in state as `last_logged_insufficient_at`); clear latch when bp recovers above threshold
- [x] 5.5 Unit tests `tests/unit/test_engine.py`: IDLE→SPREAD_OPEN (happy path), IDLE stays on capital guard (first cycle logs, second cycle silent), SPREAD_OPEN→IDLE profit-take, SPREAD_OPEN→IDLE expiry worthless, SPREAD_OPEN→IDLE max-loss; all alpaca clients mocked via `pytest-mock`

---

## 6. Monitor and summary updates

- [x] 6.1 Update `wheel/monitor.py`: when `strategy_type == "bull_put_spread"`, compute spread mid-price as `short_bid - long_ask` (conservative: values closing cost, not opening credit); add inline comment documenting the directional choice
- [x] 6.2 Update `wheel/summary.py`: when `strategy_type == "bull_put_spread"`, report spread-specific metrics row: net credit, max loss, current mid-price, unrealized P&L percentage
- [x] 6.3 Unit tests `tests/unit/test_monitor.py` and `tests/unit/test_summary.py`: spread mid calculation with known bid/ask values, summary output contains required fields for spread mode

---

## 7. Replay test layer

- [x] 7.1 Create `wheel/tools/capture_chain.py`: CLI script that fetches live SOFI option chain via `alpaca-py` and writes JSON to `tests/fixtures/option_chains/sofi_<YYYYMMDD>.json`; add `if __name__ == "__main__"` guard
- [ ] 7.2 **OPERATOR-DEFERRED**: run `python -m wheel.tools.capture_chain SOFI` once on a trading day to generate at least one real fixture file. Synthetic fixture at tests/fixtures/option_chains/sofi_synthetic.json is committed as placeholder. Real capture must be done manually at first market-open run.
- [x] 7.3 Create `tests/replay/test_spread_selection.py`: load the committed fixture, call `best_bull_put_spread` with fixture data, assert expected short/long strikes and that net credit > 0
- [x] 7.4 Create `tests/replay/test_pnl_walk.py`: if multiple fixtures exist, simulate SPREAD_OPEN state across snapshots and assert P&L calculation matches manual reference values

---

## 8. Integration smoke (paper account)

- [x] 8.1 Create `tests/integration/test_alpaca_mleg.py` with `@pytest.mark.integration` decorator
- [x] 8.2 Test body: construct a minimal `LimitOrderRequest` with `OrderClass.MLEG` for SOFI puts (tiny notional), submit to paper via `shared/alpaca_client.py`, assert order accepted (status not rejected), immediately cancel; assert cancel acknowledged
- [x] 8.3 Document execution: `pytest -m integration` (omit flag = skipped automatically via `pyproject.toml addopts`); note that paper API keys must be set in env

---

## 9. Operator documentation

- [x] 9.1 Update `README.md`: add env var table (all `WHEEL_*` vars, types, defaults), add "Running tests" section (`pip install -e ".[dev]"` → `pytest tests/`)
- [x] 9.2 Add migration note to README or `docs/migration.md`: how to manually edit `data/wheel_state.json` to flip a live CSP position to spread mode cleanly (or leave as-is for CSP completion before switching)
- [x] 9.3 Add `docs/known-limitations.md` or README section: SOFI earnings caveat (halt manually around earnings dates; automated halt is a v2 ticket — reference ticket placeholder)

---

## 10. Final wiring and smoke

- [x] 10.1 Verify `scheduler.py:wheel_task` still compiles and calls `run_cycle()` with unchanged signature (engine is sync, called via `run_in_executor` — no async refactor needed)
- [x] 10.2 Run `pytest tests/` from a clean checkout (no env vars set beyond `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`); confirm all unit + replay tests green, integration tests skipped
- [ ] 10.3 Smoke run on paper: start scheduler with `WHEEL_STRATEGY_TYPE=bull_put_spread WHEEL_SYMBOL=SOFI`; observe one full engine tick in logs; confirm capital guard does not spam, state file written correctly, no unhandled exceptions (OPERATOR-DEFERRED: requires live paper credentials and market hours)

---

## 11. Review-pass fixes (second apply pass — 2026-05-08)

- [x] 11.1 **CRITICAL**: Fix `wheel/engine.py` expiry P&L three-region accounting — add partial-loss branch (long_strike ≤ spot < short_strike), add `realized_pnl` accumulator, fix `total_premium` semantics (credit already booked at open; reverse+apply realized on loss closes only)
- [x] 11.2 **CRITICAL**: Move capital guard inside `IDLE` branch only — closing a spread (SPREAD_OPEN) must never be gated on buying power; add `realized_pnl` to fresh state and migration backfill in `wheel/state.py`
- [x] 11.3 **WARNING**: `wheel/monitor.py` profit target reads from `cfg.profit_target_pct` — replace hardcoded `0.50`; add `from wheel.config import get_config`
- [x] 11.4 **WARNING**: `wheel/state.py` symbol migration override — IDLE + explicit WHEEL_SYMBOL env → overwrite + log; non-IDLE → preserve + warn; no env var → preserve
- [x] 11.5 **WARNING**: `wheel/state.py` atomic save — temp-file + `os.replace`; temp file in same directory as STATE_FILE to avoid cross-device rename errors
- [x] 11.6 **WARNING**: `wheel/spreads.py` `_mid()` — change `bid <= 0 AND ask <= 0` to `bid <= 0 OR ask <= 0` (reject one-sided quotes)
- [x] 11.7 **NIT**: `wheel/engine.py` `_reset_spread_fields` — `contract_expiry` already in reset list (confirmed present); no change needed
- [x] 11.8 **NIT**: `wheel/spreads.py` width cap on fallback — filter candidates to `width <= cfg.spread_width`, pick widest in-bound (lowest strike); never produce wider-than-configured spread
- [x] 11.9 **NIT**: `wheel/engine.py` `_open_spread` — submit order before state mutation; return state unchanged on exception
- [x] 11.10 Tests for all above (87 passing, 1 skipped, 1 deselected; was 67 passing)
