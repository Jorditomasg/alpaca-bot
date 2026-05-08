# Wheel Specification

## Purpose

This spec covers the wheel income-strategy engine for alpaca-bot. It defines
requirements for bull-put-spread operation, state-machine transitions, capital
guards, profit-take logic, expiry/max-loss handling, symbol configuration, and
the pytest test infrastructure that gates the entire change.

---

## Requirements

### Requirement: Strategy Type Configuration

The engine SHALL read `wheel.strategy_type` from configuration and dispatch to
either the bull-put-spread path (`"bull_put_spread"`) or the legacy CSP path
(`"csp"`). Default value is `"bull_put_spread"`.

#### Scenario: Default strategy is bull-put-spread

- GIVEN no explicit `strategy_type` is set in configuration
- WHEN the wheel engine initialises
- THEN `strategy_type` resolves to `"bull_put_spread"`

#### Scenario: Explicit CSP override

- GIVEN `strategy_type: "csp"` is set in configuration
- WHEN the wheel engine initialises
- THEN the CSP execution path is selected and spread logic is bypassed entirely

---

### Requirement: Configurable Underlying Symbol

The engine SHALL load the wheel underlying symbol from `wheel.symbol`
configuration (env var or config file). No symbol SHALL be hardcoded in source
files; the previous `TSLA` constant is removed.

#### Scenario: Symbol loaded from configuration

- GIVEN `wheel.symbol` is set to `"SOFI"`
- WHEN the engine opens a new cycle
- THEN all option-chain queries and order requests target `SOFI`

#### Scenario: Default symbol is SOFI

- GIVEN `wheel.symbol` is absent from configuration
- WHEN the engine initialises
- THEN the symbol defaults to `"SOFI"`

---

### Requirement: Bull Put Spread Opening

Given state `IDLE` and sufficient buying power, the engine SHALL select a short
put strike approximately 10% OTM and a long put strike at `short_strike -
spread_width`, submit a single multi-leg credit-spread order via Alpaca
(`OrderClass.MLEG`), and transition to `SPREAD_OPEN`.

#### Scenario: Happy path — spread opens successfully

- GIVEN state is `IDLE`, buying power ≥ `spread_width × 100 × 2`, and a valid
  option chain is available
- WHEN the engine runs its opening cycle
- THEN a multi-leg order with one short put and one long put is submitted
- AND state transitions to `SPREAD_OPEN`
- AND short-leg symbol, long-leg symbol, short-strike, long-strike, net credit,
  and expiry are persisted to the state file

#### Scenario: No valid strike found in chain

- GIVEN state is `IDLE` and buying power is sufficient
- WHEN the engine queries the option chain but no strike satisfies the 10%-OTM
  window for the configured width
- THEN no order is submitted
- AND state remains `IDLE`
- AND a warning is logged with the chain query parameters

---

### Requirement: Capital Guard with Quiet Skip

The engine SHALL refuse to open a new cycle when available buying power is
below `spread_width × 100 × 2`. It SHALL log exactly ONE warning message upon
entering the under-capitalised condition and SHALL NOT log additional warnings
on subsequent cycles while the condition persists. The guard SHALL apply only
when state is `IDLE`; it SHALL NOT block closing transitions on an open spread.

#### Scenario: Buying power below threshold — first detection

- GIVEN state is `IDLE` and buying power < `spread_width × 100 × 2`
- WHEN the engine evaluates whether to open a spread
- THEN no order is submitted
- AND one warning is logged recording the buying power and threshold values
- AND state remains `IDLE`

#### Scenario: Buying power still below threshold on next cycle

- GIVEN state is `IDLE`, capital guard was already triggered in the previous
  cycle, and buying power remains below threshold
- WHEN the engine evaluates again
- THEN no order is submitted
- AND NO additional warning is logged
- AND state remains `IDLE`

#### Scenario: Buying power recovers above threshold

- GIVEN state is `IDLE` and buying power was previously below threshold
- WHEN buying power rises to ≥ `spread_width × 100 × 2`
- THEN the capital guard is cleared
- AND the engine attempts to open a spread on the next eligible cycle

#### Scenario: Capital guard does not block closing an open spread

- GIVEN state is `SPREAD_OPEN` and buying power has dropped below the open threshold
- WHEN the engine evaluates the cycle
- THEN the capital guard SHALL NOT halt the cycle
- AND profit-take, expiry, and max-loss handling SHALL proceed normally
- AND the guard re-engages only when state returns to `IDLE`

---

### Requirement: Spread State Persistence

The state file SHALL persist the following fields when `strategy_type` is
`"bull_put_spread"` and state is `SPREAD_OPEN`: `short_symbol`, `long_symbol`,
`short_strike`, `long_strike`, `spread_width`, `net_credit`, `expiry`.

#### Scenario: State file contains all spread fields after open

- GIVEN a bull put spread has been successfully submitted and filled
- WHEN the state is written to `data/`
- THEN the JSON state file contains non-null values for all seven spread fields

#### Scenario: Spread fields absent in IDLE state

- GIVEN state is `IDLE`
- WHEN the state file is read
- THEN spread-specific fields are either absent or `null`

---

### Requirement: Spread Close at 50% Profit

When the net spread mid-price (short-leg bid minus long-leg ask) is ≤ 50% of
the net credit received, the engine SHALL submit a closing order (buy-to-close
on short leg, sell-to-close on long leg) and transition to `IDLE`.

#### Scenario: Happy path — 50% profit reached

- GIVEN state is `SPREAD_OPEN` and net credit was $0.40
- WHEN the current spread mid-price is ≤ $0.20
- THEN a closing multi-leg order is submitted
- AND `cycles` increments by 1
- AND state transitions to `IDLE`
- AND `net_credit` and spread fields are cleared from state

#### Scenario: Mid-price above threshold — no action

- GIVEN state is `SPREAD_OPEN` and net credit was $0.40
- WHEN the current spread mid-price is $0.25 (> $0.20)
- THEN no closing order is submitted
- AND state remains `SPREAD_OPEN`

---

### Requirement: Spread Expiry P&L Accounting

At expiry, the engine SHALL compute realized P&L based on the underlying's
closing price relative to both strikes:

- IF `spot ≥ short_strike` THEN both legs expire worthless and realized
  profit = `net_credit`
- IF `long_strike ≤ spot < short_strike` THEN the short leg is in the money
  and realized loss = `(short_strike - spot) × 100 - net_credit` (clamped
  to `[0, max_loss]`)
- IF `spot < long_strike` THEN realized loss = `(spread_width × 100) - net_credit`
  (the full max loss)

In all three cases the engine SHALL transition to `IDLE`, increment `cycles`,
and clear all spread-specific state fields.

#### Scenario: Spot above short strike — full credit booked

- GIVEN state is `SPREAD_OPEN`, short_strike=$9, long_strike=$7, net_credit=$0.40
- WHEN expiry passes with spot=$9.50
- THEN realized profit = $40 (full net_credit)
- AND cycles increments by 1
- AND state transitions to IDLE

#### Scenario: Spot between strikes — partial loss

- GIVEN state is `SPREAD_OPEN`, short_strike=$9, long_strike=$7, net_credit=$0.40, width=$2
- WHEN expiry passes with spot=$8.20
- THEN realized loss = `(9 - 8.20) × 100 - 40 = $40` (clamped to [0, $160])
- AND cycles increments by 1
- AND state transitions to IDLE
- AND realized P&L is NOT credited as full premium

#### Scenario: Spot below long strike — full max loss

- GIVEN state is `SPREAD_OPEN`, short_strike=$9, long_strike=$7, net_credit=$0.40, width=$2
- WHEN expiry passes with spot=$6.50
- THEN realized loss = $160 (`(2 × 100) - 40`)
- AND cycles increments by 1
- AND state transitions to IDLE

---

### Requirement: State Machine Paths

For `strategy_type: "bull_put_spread"`, the state machine SHALL follow
`IDLE → SPREAD_OPEN → IDLE`. The `ASSIGNED` and `CALL_OPEN` states SHALL NOT
be reachable from spread mode. For `strategy_type: "csp"`, the legacy state
machine `IDLE → PUT_OPEN → ASSIGNED → CALL_OPEN → IDLE` SHALL remain
unmodified.

#### Scenario: Spread mode never enters ASSIGNED

- GIVEN `strategy_type` is `"bull_put_spread"` and state is `SPREAD_OPEN`
- WHEN the spread is closed (profit-take or expiry)
- THEN state transitions directly to `IDLE`
- AND `ASSIGNED` is never reached

#### Scenario: CSP mode path unchanged

- GIVEN `strategy_type` is `"csp"` and state is `PUT_OPEN`
- WHEN the short put is assigned
- THEN state transitions to `ASSIGNED`
- AND `CALL_OPEN` follows per existing CSP logic

---

### Requirement: Profit Target Configuration Consistency

Every code path that decides whether to close a spread early on profit SHALL
read the threshold from `WheelConfig.profit_target_pct`. Hardcoded percentage
values SHALL NOT exist anywhere in `wheel/`.

#### Scenario: Custom profit target propagates to monitor

- GIVEN `WHEEL_PROFIT_TARGET_PCT=25` is set in the environment
- WHEN the monitor evaluates an open spread
- THEN the monitor closes the spread when current mid-price ≤ 75% of net_credit
  (consistent with engine path)

---

### Requirement: Strike Width Cap on Fallback

When the exact configured `spread_width` is unavailable in the option chain,
the engine SHALL select the widest pair NOT EXCEEDING `spread_width`. It
SHALL NOT silently produce a wider spread than configured (which would
exceed `min_buying_power` assumptions and inflate max loss).

#### Scenario: No exact-width long leg available

- GIVEN configured spread_width=$2 and short_strike=$9, and the option chain
  offers long-strike candidates at $6.50 (width=$2.50) and $7.50 (width=$1.50)
- WHEN the engine selects a spread
- THEN the long leg is $7.50 (width=$1.50, within configured cap)
- AND $6.50 is rejected (width=$2.50 exceeds configured spread_width)
- AND the engine NEVER opens a spread wider than the configured `spread_width`

#### Scenario: No in-bound long leg exists

- GIVEN configured spread_width=$2 and short_strike=$9, and all available
  long-strike candidates would produce width > $2
- WHEN the engine evaluates the chain
- THEN no spread is selected
- AND state remains `IDLE`

---

### Requirement: Atomic State Persistence

The wheel state file SHALL be written atomically. A crash mid-write SHALL
NOT leave a corrupted or truncated JSON file on disk.

#### Scenario: Save survives an interrupted write

- GIVEN a valid state has been previously saved
- WHEN a new save is issued and the process is killed mid-write
- THEN the file on disk is either the old valid state or the new valid state
- AND it is never empty or syntactically invalid JSON

---

### Requirement: Reject Spreads Built on One-Sided Quotes

When computing a leg's mid-price, if either bid OR ask is missing or zero,
the leg SHALL be treated as unquotable and any spread that would use it
SHALL be rejected (not built, not opened, not used for close-decision).

#### Scenario: Long leg has bid=0

- GIVEN a candidate long-leg contract has bid=$0.00 ask=$0.50
- WHEN the engine evaluates the spread
- THEN the spread is rejected with a log line citing the unquotable leg
- AND no order is submitted

---

### Requirement: Symbol Migration Honors Configuration

When loading legacy state files, if `WHEEL_SYMBOL` env var is explicitly
set AND state is `IDLE` (no in-flight position), the migration SHALL
overwrite the legacy `symbol` field with the configured value.

If state is in a non-IDLE stage (`PUT_OPEN`, `ASSIGNED`, `CALL_OPEN`,
`SPREAD_OPEN`) the legacy symbol SHALL be preserved to avoid orphaning
the in-flight position.

#### Scenario: Legacy IDLE state with new symbol config

- GIVEN existing `data/wheel_state.json` has `symbol="TSLA"` and `stage="IDLE"`
- AND environment has `WHEEL_SYMBOL=SOFI`
- WHEN state is loaded
- THEN the in-memory state has `symbol="SOFI"`
- AND the next save persists `symbol="SOFI"`

#### Scenario: Legacy non-IDLE state preserves symbol

- GIVEN existing `data/wheel_state.json` has `symbol="TSLA"` and `stage="PUT_OPEN"`
- AND environment has `WHEEL_SYMBOL=SOFI`
- WHEN state is loaded
- THEN the in-memory state retains `symbol="TSLA"`
- AND a warning is logged advising the operator to wait until IDLE before flipping

---

### Requirement: Test Infrastructure

The project SHALL have a working `pytest` suite runnable via `pytest tests/`
(or `uv run pytest tests/`) from a clean checkout. The suite SHALL include unit
tests covering every state-machine transition and contract-selection scenario,
at least one replay test using a captured SOFI option-chain JSON fixture, and
integration tests gated behind `@pytest.mark.integration` (skipped by default).

#### Scenario: pytest runs green from a clean checkout

- GIVEN the repository is freshly cloned and dependencies installed
- WHEN `pytest tests/` is executed without any markers or env vars
- THEN all non-integration tests pass
- AND integration tests are automatically skipped

#### Scenario: Unit tests cover all state-machine transitions

- GIVEN the test suite
- WHEN the state-machine unit tests run
- THEN each of the following transitions has at least one test:
  `IDLE → SPREAD_OPEN` (open), `SPREAD_OPEN → IDLE` (profit-take),
  `SPREAD_OPEN → IDLE` (expiry), capital-guard refusal (stays `IDLE`)

#### Scenario: Replay test validates spread selection

- GIVEN a captured SOFI option-chain JSON fixture in `tests/fixtures/`
- WHEN the spread-selection replay test runs
- THEN the expected short and long strikes are selected
- AND the net credit is computed correctly from the fixture data
