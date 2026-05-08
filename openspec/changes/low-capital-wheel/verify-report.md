# Verify Report: low-capital-wheel

## Summary

- **Test results**: 67 passed, 1 skipped, 1 deselected, 0 failed (Python 3.14.4, pytest 9.0.3)
- **Spec coverage**: 10/10 requirements have at least one direct test
- **Tasks coverage**: 37/39 checked, 2 operator-deferred (7.2 real chain capture, 10.3 paper smoke run) — both documented
- **Import sanity**: `wheel.engine`, `wheel.spreads`, `wheel.config`, `wheel.state`, `wheel.monitor`, `wheel.summary` all import cleanly. `scheduler.py` import requires runtime deps (`httpx` for copy_trader) — not exercised in this verify environment but unchanged from main.
- **Code-level checks**:
  - Capital guard bucketed-log latch present at `wheel/engine.py:214-241`
  - MLEG order shape correct at `wheel/spreads.py:169-216` (OrderClass.MLEG, OptionLegRequest, PositionIntent.SELL_TO_OPEN/BUY_TO_OPEN for opening, BUY_TO_CLOSE/SELL_TO_CLOSE for closing)
  - State migration default at `wheel/state.py:47-51` (legacy file → `strategy_type="csp"`)
  - No TSLA hardcode in `wheel/` (only in test fixtures asserting migration path)

## CRITICAL

_None._

## WARNING

1. **Replay P&L walk test skipped**: `tests/replay/test_pnl_walk.py` requires at least 2 real `sofi_<YYYYMMDD>.json` fixtures captured on different trading days. Currently only one synthetic fixture exists. The operator must run `python -m wheel.tools.capture_chain SOFI` on two distinct trading days before this test contributes coverage. Documented in `docs/known-limitations.md` and tasks 7.2.

2. **Score threshold 0.30 unvalidated against real chains**: The synthetic fixture uses inflated premiums to satisfy `credit / max_loss ≥ 0.30`. Real SOFI chains on low-IV days may return `None` from `best_bull_put_spread` more often than expected. The threshold is a hardcoded constant in `wheel/spreads.py` — tuning may be required after first live observation.

3. **Python version drift**: Verify ran on Python 3.14.4 (linuxbrew), but the design intent is Python 3.12 (Docker base). Code is forward-compatible (no 3.14-only syntax), but production parity should be validated when deploying via Dockerfile. No action required for this change, just a note.

4. **Integration tests never executed in this verify**: `tests/integration/test_alpaca_mleg.py` is correctly marked `@pytest.mark.integration` and deselected by default. Operator must run `pytest -m integration` against a real Alpaca paper account to confirm the constructed MLEG order is accepted by the API. Skipping this leaves a small risk that an SDK-level field shape mismatch goes undetected until the first live cycle.

## SUGGESTION

1. **Add CI workflow**: `.github/workflows/test.yml` running `pytest` on push would gate regressions. Out of scope here but a low-cost next step.
2. **Earnings-calendar guard (v2)**: SOFI earnings during contract life can blow the spread to max loss. A small calendar check in `_run_spread_cycle` to skip openings within N days of earnings would meaningfully reduce tail risk. Documented in `docs/known-limitations.md`.
3. **Auto-symbol screening (v2)**: Currently the symbol is explicit config. A future enhancement could auto-pick a liquid sub-$15 underlying with healthy IV — leveraging the existing scorer pattern from `copy_trader/`.

## Spec → Test Map

| Requirement | Tests |
|-------------|-------|
| Strategy Type Configuration — default `bull_put_spread` | `test_default_strategy_type` |
| Strategy Type Configuration — explicit CSP override | `test_env_override_strategy_type`, `test_dispatch_calls_csp_cycle` |
| Configurable Underlying Symbol — loaded from config | `test_env_override_symbol` |
| Configurable Underlying Symbol — default SOFI | `test_default_symbol` |
| Configurable Underlying Symbol — no TSLA hardcode | `test_no_tsla_hardcode_in_fresh_state` |
| Bull Put Spread Opening — happy path | `test_idle_to_spread_open_happy_path`, `test_happy_path_selects_correct_strikes`, `test_build_open_order_shape` |
| Bull Put Spread Opening — no valid strike | `test_idle_stays_when_no_spread_found`, `test_empty_chain_returns_none`, `test_no_contracts_in_dte_range_returns_none`, `test_score_threshold_rejection` |
| Capital Guard — first detection logs | `test_capital_guard_logs_on_first_insufficient` |
| Capital Guard — silent on subsequent same-bp cycles | `test_capital_guard_silent_on_second_cycle_same_bp` |
| Capital Guard — relog on bp change | `test_capital_guard_relogs_when_bp_changes` |
| Capital Guard — clears on recovery | `test_capital_guard_clears_on_recovery` |
| Spread State Persistence — all fields after open | `test_idle_to_spread_open_happy_path`, `test_save_and_load_round_trip` |
| Spread State Persistence — null in IDLE | `test_fresh_state_spread_fields_are_null` |
| Spread Close at 50% — profit reached | `test_spread_open_to_idle_profit_take`, `test_spread_mid_price_below_target_triggers_close`, `test_spread_mid_exactly_at_boundary_triggers_close` |
| Spread Close at 50% — above threshold no-op | `test_spread_open_stays_when_mid_above_target`, `test_spread_mid_price_above_target_no_close` |
| Spread Expiry Worthless | `test_spread_expires_worthless` |
| Spread Max-Loss Handling | `test_spread_max_loss_at_expiry` |
| State Machine Paths — spread mode never enters ASSIGNED | `test_dispatch_calls_spread_cycle`, `test_csp_does_not_reach_spread_open` |
| State Machine Paths — CSP mode unchanged | `test_csp_idle_tries_to_open_put`, `test_csp_early_close_still_works` |
| Test Infrastructure — pytest green | Verified by full suite run (67 passed) |
| Test Infrastructure — all transitions covered | Verified by transition test set (open, profit-take, expiry, max-loss, capital guard) |
| Test Infrastructure — replay test exists | `test_spread_selection_from_synthetic_fixture`, `test_spread_fixture_net_credit_is_plausible` |
| Test Infrastructure — integration gated | `tests/integration/test_alpaca_mleg.py` deselected by default (1 deselected in run output) |

## Conclusion

**PASS WITH WARNINGS**

The change is implementation-complete and spec-compliant. All money-flow paths have direct test coverage. The 4 warnings are operator-action items (capture real fixtures, run paper smoke, validate threshold under real conditions) rather than code defects, and they are tracked in `tasks.md` and `docs/known-limitations.md`.

Recommend: proceed to `sdd-archive` after the operator has done at least one paper smoke run to validate that Alpaca actually accepts the MLEG order shape we constructed (warning #4). Archive without that run is acceptable but carries the small residual risk noted above.
