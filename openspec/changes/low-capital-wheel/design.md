# Design: low-capital-wheel

> Phase: `sdd-design` — concrete architecture for the bull-put-spread wheel.
> Reads: `proposal.md`, `explore.md`. Companion to `spec.md`. Predecessor of `tasks.md`.

This document describes HOW the change is implemented. It does NOT enumerate tasks (that lives in `tasks.md`).

---

## 1. Architecture overview

The wheel cycle today is a single state machine driven by `run_cycle(state)`. After this change, `run_cycle` becomes a thin **dispatcher** that branches on `state["strategy_type"]` and delegates to one of two engines:

- `_run_csp_cycle(state)` — the existing four-state CSP machine, untouched in behavior.
- `_run_spread_cycle(state)` — a new two-state machine for `bull_put_spread`.

The async surface (`scheduler.py:wheel_task`) does not change. The sync engine + `run_in_executor` pattern is preserved.

```
           ┌──────────────────────────────────────────────────────┐
           │                  scheduler.wheel_task                 │
           │   (async, market_hours gate, 15-min sleep loop)       │
           └──────────────────────────────────────────────────────┘
                                   │
                                   ▼
                    wheel_monitor.check_early_close(state)
                                   │
                                   ▼
                       wheel_engine.run_cycle(state)
                                   │
                ┌──────────────────┴──────────────────┐
                │                                     │
        strategy_type == "csp"          strategy_type == "bull_put_spread"
                │                                     │
                ▼                                     ▼
   ┌──────────────────────┐            ┌─────────────────────────────┐
   │  CSP state machine   │            │  Spread state machine        │
   │                      │            │                              │
   │  IDLE ─► PUT_OPEN    │            │  IDLE ─► SPREAD_OPEN ─► IDLE │
   │   ▲       │          │            │           │                  │
   │   │       ▼          │            │           ▼                  │
   │   │   ASSIGNED       │            │  (profit-take 50% or expiry) │
   │   │       │          │            │                              │
   │   │       ▼          │            └─────────────────────────────┘
   │   └── CALL_OPEN      │
   └──────────────────────┘
```

CSP `IDLE → PUT_OPEN → ASSIGNED → CALL_OPEN → IDLE` is preserved bit-for-bit. Spread mode collapses the cycle: `bull_put_spread` cannot be assigned (defined-risk), so the `ASSIGNED` and `CALL_OPEN` states are unreachable in that branch.

Capital guard runs as the FIRST step inside both branches, before any market data or order-construction calls. If buying power < threshold, the cycle returns the state unchanged after a one-shot log and the next tick re-checks.

---

## 2. Module layout

### New files

| Path | Responsibility |
|------|----------------|
| `wheel/spreads.py` | Multi-leg contract pair selection + `OptionLegRequest` payload construction. Public API: `best_bull_put_spread(symbol, current_price, width, dte_range)`, `build_open_order(short, long_, limit_price)`, `build_close_order(short_sym, long_sym, limit_price)`, `spread_mid_price(short_sym, long_sym)`. |
| `wheel/config.py` | Centralised env-var reader. Exposes a single `WheelConfig` dataclass. No imports from `wheel.*` (avoids cycles). Defaults documented in §3. |
| `wheel/tools/__init__.py` | Empty marker. |
| `wheel/tools/capture_chain.py` | Operator script: snapshot live SOFI option chain to JSON for replay tests. Run via `python -m wheel.tools.capture_chain SOFI`. |
| `tests/__init__.py` | Empty marker. |
| `tests/conftest.py` | Shared fixtures: `frozen_clock`, `mock_trading_client`, `mock_option_data_client`, `load_chain_fixture`. |
| `tests/unit/test_engine_dispatch.py` | Strategy-type dispatch + capital guard. |
| `tests/unit/test_engine_csp.py` | Legacy CSP non-regression smoke. |
| `tests/unit/test_engine_spread.py` | Spread state-machine transitions (open / profit-take / expiry / refusal). |
| `tests/unit/test_spreads.py` | Spread selection, mleg payload shape, mid-price math. |
| `tests/unit/test_state_migration.py` | Backward-compat: old TSLA/CSP state file loads cleanly. |
| `tests/unit/test_capital_guard.py` | One-shot log, re-trigger on buying-power change. |
| `tests/replay/test_spread_selection_replay.py` | Runs `best_bull_put_spread` against captured chain fixtures. |
| `tests/replay/test_monitor_replay.py` | Runs profit-take logic against snapshotted bid/ask sequences. |
| `tests/integration/test_paper_mleg_smoke.py` | `@pytest.mark.integration` — submits a real mleg order to Alpaca paper, cancels it, asserts the API accepted it. |
| `tests/fixtures/option_chains/sofi_<date>.json` | Real captured chains. At least one committed at change-time. |
| `pyproject.toml` | Modern packaging + tool config. Holds dev deps (`pytest`, `pytest-asyncio`, `pytest-mock`), `[tool.pytest.ini_options]` block, marker registration. |

### Modified files

| Path | Change |
|------|--------|
| `wheel/state.py` | Remove `"TSLA"` hardcode. Schema gains `strategy_type`, `short_*`, `long_*`, `net_credit`, `max_loss`, `last_logged_insufficient_at`. `load()` reads `WheelConfig.symbol` for the default. Add a one-shot migration in `load()` that fills `strategy_type="csp"` for existing files (preserves running positions). |
| `wheel/engine.py` | Add `run_cycle` dispatcher. Move existing CSP body into `_run_csp_cycle`. Add `_run_spread_cycle` with `IDLE → SPREAD_OPEN → IDLE` transitions. Capital guard with one-shot logging. |
| `wheel/options.py` | No new public functions. Refactor `_find_contract` to take `min_strike`/`max_strike` instead of `target_strike ± 5` (so spreads can request a wider window). Keep `best_put` / `best_call` working for CSP via a thin wrapper. |
| `wheel/monitor.py` | Add a strategy-aware branch. For `SPREAD_OPEN`, compute `current_spread_cost = spreads.spread_mid_price(short, long)` and compare against `state["net_credit"] / 100 * 0.50`. Use `spreads.build_close_order` to flatten. |
| `wheel/summary.py` | When `strategy_type == "bull_put_spread"` print spread-specific block: short/long symbols, net credit, max loss, current spread P&L. CSP block unchanged. |
| `scheduler.py` | Drop `TSLA = "TSLA"`. Wheel symbol comes from `WheelConfig`. (Trailing fallback still uses `"TSLA"` — out of scope.) |
| `wheel/__init__.py` (NEW or extended) | Re-export `run_cycle`, `check_early_close`, `print_summary`, `WheelConfig`. |
| `requirements.txt` | Untouched at runtime; dev deps live in `pyproject.toml`. |

---

## 3. Config surface

All wheel-mode knobs are environment variables. `wheel/config.py` reads them once and returns a frozen dataclass. No magic strings inside the engine.

```python
# wheel/config.py
from dataclasses import dataclass
from functools import lru_cache
import os

@dataclass(frozen=True)
class WheelConfig:
    strategy_type: str           # "bull_put_spread" | "csp"
    symbol: str                  # e.g. "SOFI"
    spread_width: float          # dollars between long and short strike
    min_buying_power: float      # absolute floor; default = width * 100 * 2
    target_dte_min: int          # days
    target_dte_max: int          # days
    profit_target_pct: float     # 0..100
    target_otm_pct: float        # 0..1, default 0.10 (10% OTM)

@lru_cache(maxsize=1)
def get_config() -> WheelConfig:
    width = float(os.getenv("WHEEL_SPREAD_WIDTH", "2"))
    default_min_bp = width * 100 * 2
    return WheelConfig(
        strategy_type=os.getenv("WHEEL_STRATEGY_TYPE", "bull_put_spread"),
        symbol=os.getenv("WHEEL_SYMBOL", "SOFI"),
        spread_width=width,
        min_buying_power=float(os.getenv("WHEEL_MIN_BUYING_POWER", str(default_min_bp))),
        target_dte_min=int(os.getenv("WHEEL_TARGET_DTE_MIN", "14")),
        target_dte_max=int(os.getenv("WHEEL_TARGET_DTE_MAX", "28")),
        profit_target_pct=float(os.getenv("WHEEL_PROFIT_TARGET_PCT", "50")),
        target_otm_pct=float(os.getenv("WHEEL_TARGET_OTM_PCT", "0.10")),
    )
```

| Env var | Default | Notes |
|---------|---------|-------|
| `WHEEL_STRATEGY_TYPE` | `bull_put_spread` | `csp` opts back into legacy. |
| `WHEEL_SYMBOL` | `SOFI` | Replaces TSLA hardcode in state.py:14 and scheduler.py:29. |
| `WHEEL_SPREAD_WIDTH` | `2` | Dollars. SOFI chain has $0.50/$1 spacing → $2-wide always constructible. |
| `WHEEL_MIN_BUYING_POWER` | `width * 100 * 2` (= $400 default) | Capital guard floor. |
| `WHEEL_TARGET_DTE_MIN` | `14` | Days to expiry, lower bound. |
| `WHEEL_TARGET_DTE_MAX` | `28` | Days to expiry, upper bound. |
| `WHEEL_PROFIT_TARGET_PCT` | `50` | Trigger for early close. |
| `WHEEL_TARGET_OTM_PCT` | `0.10` | Distance from spot for short strike. |

`get_config()` is cached so that tests can monkeypatch `os.environ` and call `get_config.cache_clear()` between cases. Production code never imports module-level constants — it always calls `get_config()`.

---

## 4. Spread selection algorithm

Goal: pick the short/long pair that maximises **risk-adjusted credit** (credit divided by max loss) within configured DTE and OTM constraints.

```text
function best_bull_put_spread(symbol, current_price, width, dte_min, dte_max, target_otm_pct) -> dict | None:
    target_short_strike = current_price * (1 - target_otm_pct)              # e.g. spot=10 → 9.0

    # Pull a generous window so we always have both legs available
    candidates = list_put_contracts(
        symbol,
        min_strike = target_short_strike - width - 1,                       # room for the long leg
        max_strike = target_short_strike + 1,                               # one notch above target
        dte_min, dte_max,
    )
    if not candidates: return None

    # Group by expiry: a spread must use legs with the SAME expiration date
    by_expiry = group_by(candidates, key=expiry)

    best = None
    for expiry, contracts in by_expiry.items():
        contracts_by_strike = sort_by_strike(contracts)

        # Pick short: highest strike <= target_short_strike (closest from below)
        shorts = [c for c in contracts_by_strike if c.strike <= target_short_strike]
        if not shorts: continue
        short = shorts[-1]

        # Pick long: strike == short.strike - width if exact; else fallback to next valid pair
        long_target = short.strike - width
        longs = [c for c in contracts_by_strike if c.strike == long_target]
        if not longs:
            # Fallback: any strike strictly less than short, closest to long_target
            below = [c for c in contracts_by_strike if c.strike < short.strike]
            if not below: continue
            long_ = min(below, key=lambda c: abs(c.strike - long_target))
            actual_width = short.strike - long_.strike
        else:
            long_ = longs[0]
            actual_width = width

        short_q = quote(short.symbol)
        long_q  = quote(long_.symbol)
        if short_q is None or long_q is None: continue

        credit   = mid(short_q) - mid(long_q)              # net credit per share
        if credit <= 0: continue                           # never pay to open a credit spread
        max_loss = (actual_width * 100) - (credit * 100)
        score    = (credit * 100) / max_loss               # credit/risk ratio

        if score < 0.30:
            log("[SPREAD] reject {short.strike}/{long_.strike}@{expiry} score={score:.2f} <0.30")
            continue

        candidate = {
            "short_symbol": short.symbol,
            "short_strike": short.strike,
            "long_symbol":  long_.symbol,
            "long_strike":  long_.strike,
            "expiry":       expiry,
            "net_credit":   credit * 100,                  # dollars per spread
            "max_loss":     max_loss,                      # dollars per spread
            "width":        actual_width,
            "score":        score,
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate

    return best
```

Edge cases:
- **No exact-width long leg** → fallback to closest below; recompute `actual_width`. Keep going.
- **Bid-ask crossed / zero quote** → skip the candidate, do not pick.
- **All candidates score below 0.30** → return `None` and the engine logs `[WHEEL] no decent spread today` and stays IDLE.
- **Negative net credit** → skip (we never pay to open a credit spread).

---

## 5. Multi-leg order construction

Built on `alpaca-py` Level 3 multi-leg API.

```python
# wheel/spreads.py
from alpaca.trading.requests import LimitOrderRequest, OptionLegRequest
from alpaca.trading.enums import (
    OrderSide, OrderClass, TimeInForce, PositionIntent,
)

def build_open_order(short_symbol: str, long_symbol: str, limit_credit: float) -> LimitOrderRequest:
    """
    Sell a bull put spread:
      - SELL_TO_OPEN the short put (the higher strike)
      - BUY_TO_OPEN  the long  put (the lower  strike)
    Net price = credit received, expressed POSITIVE on a SELL mleg.
    """
    return LimitOrderRequest(
        qty=1,
        order_class=OrderClass.MLEG,
        time_in_force=TimeInForce.DAY,
        limit_price=round(limit_credit, 2),
        legs=[
            OptionLegRequest(
                symbol=short_symbol,
                ratio_qty=1,
                side=OrderSide.SELL,
                position_intent=PositionIntent.SELL_TO_OPEN,
            ),
            OptionLegRequest(
                symbol=long_symbol,
                ratio_qty=1,
                side=OrderSide.BUY,
                position_intent=PositionIntent.BUY_TO_OPEN,
            ),
        ],
    )

def build_close_order(short_symbol: str, long_symbol: str, limit_debit: float) -> LimitOrderRequest:
    """Close: BUY_TO_CLOSE the short, SELL_TO_CLOSE the long. Net price = debit paid."""
    return LimitOrderRequest(
        qty=1,
        order_class=OrderClass.MLEG,
        time_in_force=TimeInForce.DAY,
        limit_price=round(limit_debit, 2),
        legs=[
            OptionLegRequest(
                symbol=short_symbol,
                ratio_qty=1,
                side=OrderSide.BUY,
                position_intent=PositionIntent.BUY_TO_CLOSE,
            ),
            OptionLegRequest(
                symbol=long_symbol,
                ratio_qty=1,
                side=OrderSide.SELL,
                position_intent=PositionIntent.SELL_TO_CLOSE,
            ),
        ],
    )
```

Submitted via the existing sync `client.submit_order(...)` call. Quantity lives at the order level; `ratio_qty=1` on each leg means 1:1. For multi-contract sizing later we change `qty` to N and keep `ratio_qty=1`.

---

## 6. State schema (after migration)

`data/wheel_state.json` becomes a discriminated record:

```json
{
  "strategy_type": "bull_put_spread",
  "stage": "SPREAD_OPEN",
  "symbol": "SOFI",
  "cycles": 3,
  "total_premium": 142.50,

  "short_symbol":  "SOFI260117P00009000",
  "short_strike":  9.0,
  "long_symbol":   "SOFI260117P00007000",
  "long_strike":   7.0,
  "contract_expiry": "2026-01-17",
  "net_credit":    62.00,
  "max_loss":      138.00,
  "spread_width":  2.0,

  "premium_received": 62.00,

  "contract_symbol": null,
  "contract_strike": null,
  "cost_basis":      null,
  "shares_owned":    0,

  "last_logged_insufficient_at": null
}
```

Legacy CSP fields (`contract_symbol`, `contract_strike`, `cost_basis`, `shares_owned`) are kept on the schema and are simply unused in spread mode (set to `null` / `0`). This keeps `summary.py` simpler and gives a clean migration path: an existing TSLA/CSP file loads with no field renames.

`stage` valid values:
- CSP: `IDLE | PUT_OPEN | ASSIGNED | CALL_OPEN`
- Spread: `IDLE | SPREAD_OPEN`

`premium_received` is reused for both modes (it is "the premium currently at risk in the open contract"). `net_credit` and `max_loss` are spread-only.

---

## 7. Capital guard (one-shot logging)

The guard sits at the top of both `_run_csp_cycle` and `_run_spread_cycle`. Pseudocode:

```python
def _capital_guard(state, required, label) -> bool:
    """Return True if cycle should HALT (insufficient capital), False to proceed."""
    bp = float(alpaca_client.trading().get_account().buying_power)
    if bp >= required:
        # Recovered → clear the latch so future shortfalls are logged again
        state["last_logged_insufficient_at"] = None
        return False

    # Insufficient. Log only on transition (latch by bucketed bp + cycles).
    bucket = (round(bp, 0), state.get("cycles", 0))
    last   = state.get("last_logged_insufficient_at")
    if last != bucket:
        print(f"[WHEEL] Insufficient buying power: ${bp:.2f} < ${required:.2f} ({label}) — skipping cycle")
        state["last_logged_insufficient_at"] = bucket
    return True
```

`bucket` is `(rounded_buying_power, cycles)`:
- Identical buying power on consecutive ticks → same bucket → silent.
- Buying power changes by ≥ $1 → new bucket → re-log (something material changed).
- Cycle counter advances (closed a position, etc.) → re-log.
- Recovery to `bp >= required` → reset to `None` so next shortfall logs immediately.

---

## 8. Test environment design

### Layout

```
tests/
├── __init__.py
├── conftest.py                    # shared fixtures
├── fixtures/
│   └── option_chains/
│       ├── sofi_2026-05-08.json   # captured by wheel/tools/capture_chain.py
│       └── sofi_low-iv-day.json   # second snapshot for variety
├── unit/
│   ├── __init__.py
│   ├── test_engine_dispatch.py
│   ├── test_engine_csp.py
│   ├── test_engine_spread.py
│   ├── test_spreads.py
│   ├── test_state_migration.py
│   └── test_capital_guard.py
├── replay/
│   ├── __init__.py
│   ├── test_spread_selection_replay.py
│   └── test_monitor_replay.py
└── integration/
    ├── __init__.py
    └── test_paper_mleg_smoke.py
```

### `pyproject.toml` essentials

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "pytest-mock>=3.12"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q -ra -m 'not integration'"
markers = [
  "integration: hits the real Alpaca paper API (skipped by default)",
  "replay: runs against captured option-chain JSON fixtures",
]
asyncio_mode = "auto"
```

`addopts = -m 'not integration'` means `pytest` runs unit + replay by default. The integration suite is opt-in: `pytest -m integration`.

### `conftest.py` shape

```python
# tests/conftest.py
import json, pathlib, pytest
from unittest.mock import MagicMock

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

@pytest.fixture
def load_chain_fixture():
    def _load(name: str) -> dict:
        return json.loads((FIXTURES / "option_chains" / name).read_text())
    return _load

@pytest.fixture
def mock_trading_client(mocker):
    client = MagicMock()
    mocker.patch("shared.alpaca_client.trading", return_value=client)
    return client

@pytest.fixture
def mock_option_data_client(mocker):
    client = MagicMock()
    mocker.patch("shared.alpaca_client.option_data", return_value=client)
    return client

@pytest.fixture(autouse=True)
def _reset_wheel_config_cache():
    from wheel.config import get_config
    get_config.cache_clear()
    yield
    get_config.cache_clear()

@pytest.fixture
def wheel_env(monkeypatch):
    """Helper to set a coherent wheel env in one call."""
    def _set(**kwargs):
        defaults = {
            "WHEEL_STRATEGY_TYPE": "bull_put_spread",
            "WHEEL_SYMBOL": "SOFI",
            "WHEEL_SPREAD_WIDTH": "2",
        }
        defaults.update({k.upper(): str(v) for k, v in kwargs.items()})
        for k, v in defaults.items():
            monkeypatch.setenv(k, v)
    return _set
```

### Layer responsibilities

**Unit (`tests/unit/`)** — fully mocked clients. Cover, at minimum:
- Dispatch picks the correct branch based on `strategy_type`.
- Capital guard: refuses, logs ONCE, re-logs on bp change, releases on recovery.
- Spread state transitions: `IDLE → SPREAD_OPEN`, profit-take 50%, expiry close, refusal when score < 0.30.
- Spread selection: exact-width pair, fallback when long leg missing, skip when net credit ≤ 0.
- mleg payload: shape, `OrderClass.MLEG`, leg sides, position intents.
- Migration: legacy TSLA/CSP state loads with `strategy_type="csp"` injected.

**Replay (`tests/replay/`)** — fixture-driven. The capture script writes a JSON like:
```json
{
  "captured_at": "2026-05-08T18:30:00Z",
  "underlying": "SOFI",
  "spot_price": 9.42,
  "contracts": [
    {"symbol":"SOFI260117P00009000","type":"put","strike":9.0,
     "expiration_date":"2026-01-17","bid":0.32,"ask":0.36},
    ...
  ]
}
```
Tests patch `alpaca_client.trading()` and `alpaca_client.option_data()` so contract list and quotes come from the fixture, then run `best_bull_put_spread` and assert the chosen pair / credit.

**Integration (`tests/integration/`)** — `@pytest.mark.integration`, skipped by default. Connects to real Alpaca paper, builds a far-OTM SOFI bull put spread, submits, asserts `order.status` is one of `(new, accepted, accepted_for_bidding)`, then cancels. Validates the SDK call matches what Alpaca actually accepts. Run manually before deploying.

---

## 9. Migration / backward compatibility

The migration runs in `wheel/state.py:load()`:

```python
def load() -> dict:
    cfg = get_config()
    if STATE_FILE.exists():
        s = json.loads(STATE_FILE.read_text())
        # Backfill new fields on legacy state
        if "strategy_type" not in s:
            s["strategy_type"] = "csp"   # preserve any in-flight CSP cycle
            print("[WHEEL] Legacy state detected → strategy_type defaulted to 'csp'. "
                  "Set WHEEL_STRATEGY_TYPE=bull_put_spread on the next fresh cycle.")
        s.setdefault("short_symbol", None)
        s.setdefault("short_strike", None)
        s.setdefault("long_symbol", None)
        s.setdefault("long_strike", None)
        s.setdefault("net_credit", 0.0)
        s.setdefault("max_loss", 0.0)
        s.setdefault("spread_width", cfg.spread_width)
        s.setdefault("last_logged_insufficient_at", None)
        return s
    # Fresh state uses configured strategy + symbol
    return {
        "strategy_type": cfg.strategy_type,
        "stage": "IDLE",
        "symbol": cfg.symbol,
        ...
    }
```

Two paths:

1. **Existing state in `IDLE` (or freshly closed)** → `strategy_type` defaults to `csp`. The user is told (single log line) to switch via env var. The next cycle still runs CSP on TSLA. To migrate, the operator sets `WHEEL_STRATEGY_TYPE=bull_put_spread` and `WHEEL_SYMBOL=SOFI` and either deletes the state file or waits for the next CSP cycle to complete.
2. **Existing state in `PUT_OPEN | ASSIGNED | CALL_OPEN`** → `strategy_type=csp` is the safe default. The wheel finishes the in-flight CSP cycle on TSLA. After the cycle returns to `IDLE`, the operator switches strategy and symbol via env vars and (manually) clears the state file or sets `WHEEL_SYMBOL=SOFI` to start fresh. We do NOT auto-switch strategy mid-cycle — that would orphan an open option.

This rule keeps real money flow safe: nobody loses an in-flight position because they pulled main.

---

## 10. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| **Stale mid-price outside RTH.** Alpaca paper option quotes can be hours stale after the close. Mid-price profit-take could fire on a misleading price. | `wheel_task` already gates on `market_hours.is_market_open()`. The monitor inherits that gate. Add a quote-age check inside `spread_mid_price` if the SDK exposes timestamp; otherwise rely on the market-hours gate. Document that early-close fires only during RTH. |
| **Partial fills on multi-leg.** | Alpaca executes mleg orders **atomically** — both legs fill or neither does. Documented in their Level 3 docs. We rely on this and assert it in the integration smoke (the response should never show one leg filled and the other not). If a future SDK update breaks the guarantee we need a reconciliation pass — out of scope today, noted. |
| **Strike availability gaps.** SOFI may temporarily lack the exact long leg at `short - width`. | Algorithm falls back to "closest below short" and recomputes `actual_width`. Width drift is tolerated up to `width + 1`; beyond that we skip. |
| **Score threshold (0.30) too aggressive.** | Threshold is a constant in this iteration. If observed pass rate is too low we lower it via a config knob in a follow-up. Logged on every rejection so we can tune from real data. |
| **Earnings event during contract life.** SOFI earnings can spike IV and blow the spread to max loss. | Out of scope for this change (no earnings calendar integration). Documented as a known limitation. v2 ticket: pre-trade earnings filter. |
| **`get_config()` cache vs. tests.** Tests can leak env across cases if the cache is stale. | `tests/conftest.py` has an autouse fixture that calls `get_config.cache_clear()` before and after each test. |
| **CSP regression.** Refactoring `_find_contract` could break legacy CSP. | `tests/unit/test_engine_csp.py` is a non-regression smoke (mocked) executed on every run. Behavioural goal: byte-identical orders for the CSP branch. |
| **Capital guard log spam regression.** A naive boolean latch logs once and never recovers. | Bucket key is `(rounded_bp, cycles)` so any material change re-triggers. Recovery clears the latch. Covered by `test_capital_guard.py`. |

---

## ADRs (decision log)

### ADR-1: Dispatcher pattern over polymorphism
Two strategies (`csp`, `bull_put_spread`) share ~30% of code (capital guard, state file IO, summary skeleton). A single dispatcher in `run_cycle` with two private functions keeps the call tree obvious and avoids inventing a `Strategy` ABC for two implementations. Rejected: class-per-strategy with a registry — over-engineering at N=2.

### ADR-2: `wheel/config.py` over scattered `os.getenv`
Single source of truth, single `get_config()` call point, easy to mock in tests via `cache_clear()` + `monkeypatch`. Rejected: passing config dict around — leaks knob names into call sites and complicates non-regression of the CSP path.

### ADR-3: Migration defaults to `csp`, not `bull_put_spread`
Safer default: existing state files were written by the old engine, so they describe a CSP position. Auto-switching strategy mid-cycle would orphan an open option (we have the contract symbol but the wrong state machine to track it). The migration log line tells the operator how to switch on a clean cycle. Rejected: auto-detect by inspecting open positions — too clever, fragile.

### ADR-4: Score threshold (credit/max-loss ≥ 0.30) is a constant in v1
Hardcoded, with a clear log line on rejection. We need real production data to decide where the threshold should live. Rejected: a configurable `WHEEL_MIN_SCORE` env var — premature; ship the constant, observe, then expose if needed.

### ADR-5: Run sync engine inside `wheel_task` — no async refactor
The existing `scheduler.py:wheel_task` is async, but `run_cycle` is sync and called directly. That is fine: the cycle is short and runs every 15 min. Rejected: rewriting engine in async — no benefit, big diff, breaks the "trailing/copy_trader untouched" success criterion.

### ADR-6: Use `LimitOrderRequest` (not `MarketOrderRequest`) for both open and close
Mleg orders should be priced — opening at market on a thinly-traded option chain risks paying through the spread. We submit a limit at the computed mid for opens (credit) and at a small premium above mid for closes (debit). Rejected: market mleg open — slippage risk.

### ADR-7: Pytest config in `pyproject.toml`, not `pytest.ini`
Modern Python tooling consolidates config in `pyproject.toml`. We add a `[project]` block and a `[tool.pytest.ini_options]` block. `requirements.txt` stays as the runtime install path; dev deps live under `[project.optional-dependencies].dev` and install via `pip install -e '.[dev]'`. Rejected: separate `pytest.ini` — splits config across files.

---

## File-by-file summary

```
NEW   wheel/spreads.py                      ~120 LOC
NEW   wheel/config.py                       ~40 LOC
NEW   wheel/tools/__init__.py               empty
NEW   wheel/tools/capture_chain.py          ~60 LOC
MOD   wheel/state.py                        ~+30 LOC (migration + new fields)
MOD   wheel/engine.py                       ~+80 LOC (dispatcher + spread cycle + guard)
MOD   wheel/options.py                      ~+10 LOC (strike-window param)
MOD   wheel/monitor.py                      ~+40 LOC (spread branch)
MOD   wheel/summary.py                      ~+25 LOC (spread block)
MOD   scheduler.py                          ~-2 LOC (drop TSLA constant)
NEW   wheel/__init__.py                     ~10 LOC re-exports
NEW   pyproject.toml                        ~30 LOC
NEW   tests/                                full tree per §8
```

End of design.
