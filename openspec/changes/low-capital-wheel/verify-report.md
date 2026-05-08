# Verify Report: low-capital-wheel (post-review pass)

## Summary

- **Test results**: 87 passed, 1 skipped, 1 deselected, 0 failed (Python 3.14.4, pytest 9.0.3) — up from 67 in the first pass (+20 tests covering the review-driven fixes)
- **Spec coverage**: 16/16 requirements have at least one direct test (was 10/10; spec was extended with 6 new requirements + 1 refinement during the review pass)
- **Tasks coverage**: section 11 added for the review fixes; all section-11 tasks checked. Operator-deferred items (real chain capture, paper smoke run) unchanged.
- **Review findings status**: all 9 (2 CRITICAL + 4 WARNING + 3 NIT) addressed and tested.

## CRITICAL fixes — verified

| Finding | File:Line | Verification |
|---------|-----------|--------------|
| Expiry P&L mis-accounted in partial-loss zone | `wheel/engine.py:157-188` | Three-region handling: `price >= short_strike` (worthless), `price >= long_strike` (partial, intrinsic-based clamp), else (full max loss). `total_premium` reverses the open-time credit on losing closes; `realized_pnl` accumulator added. Tests assert distinct numeric outcomes per region. |
| Capital guard blocks spread close | `wheel/engine.py:70-78` | Guard moved inside the `IDLE` branch with explanatory comment at line 76: "closing a spread releases collateral and must never be blocked." Test confirms SPREAD_OPEN cycle proceeds with BP=$50. |

## WARNING fixes — verified

| Finding | File | Verification |
|---------|------|--------------|
| Monitor hardcodes 50% | `wheel/monitor.py` | Reads `cfg.profit_target_pct`. Test with `WHEEL_PROFIT_TARGET_PCT=25` confirms 75%-of-credit threshold. |
| Symbol migration no-op | `wheel/state.py` | IDLE state with explicit `WHEEL_SYMBOL` overwrites legacy symbol; non-IDLE preserves and warns. Three tests cover the matrix. |
| Non-atomic state save | `wheel/state.py:120-136` | `tempfile.mkstemp` in same dir + `os.replace` (atomic on POSIX and Windows when same filesystem). |
| `_mid` accepts half-quoted | `wheel/spreads.py` | Changed `bid <= 0 AND ask <= 0` → `bid <= 0 OR ask <= 0`. Test confirms rejection. |

## NIT fixes — verified

- `_reset_spread_fields` clears `contract_expiry` (no stale leak into IDLE)
- Width cap on fallback: never produces a wider spread than configured
- `_open_spread` defers state mutation until after `submit_order` succeeds

## Spec → Test Map (additions over first pass)

| New requirement | Tests |
|-----------------|-------|
| Three-region expiry P&L | `test_spread_expires_worthless_above_short`, `test_spread_partial_loss_between_strikes`, `test_spread_full_max_loss_below_long`, `test_total_premium_reversed_on_losing_close` |
| Capital guard scope (IDLE only) | `test_capital_guard_does_not_block_spread_close`, `test_capital_guard_still_blocks_idle_open` |
| Profit target consistency | `test_monitor_reads_profit_target_from_config`, `test_default_profit_target_unchanged` |
| Strike width cap | `test_fallback_never_exceeds_configured_width`, `test_fallback_picks_widest_qualifying` |
| Atomic state save | `test_save_does_not_leave_tmp_files`, `test_save_round_trip_after_atomic_write` |
| One-sided quote rejection | `test_mid_rejects_zero_bid`, `test_mid_rejects_zero_ask`, `test_spread_rejected_when_short_unquotable` |
| Symbol migration override | `test_legacy_idle_with_env_overwrites_symbol`, `test_legacy_non_idle_preserves_symbol`, `test_no_env_var_preserves_symbol` |

## Remaining open items (operator-deferred, unchanged)

1. **Real chain capture** (task 7.2): `python -m wheel.tools.capture_chain SOFI` in market hours. Replay P&L walk test will activate once 2 fixtures from different days exist.
2. **Paper smoke run** (task 10.3): `WHEEL_STRATEGY_TYPE=bull_put_spread WHEEL_SYMBOL=SOFI python main.py` — validates Alpaca accepts the constructed MLEG order shape end-to-end.
3. **Integration test execution** (task 8.x): `pytest -m integration` against paper account. Code constructs the MLEG order; only paper-side acceptance remains unverified.
4. **Score threshold tuning** (`docs/known-limitations.md`): 0.30 may be too tight on low-IV days. Observe live, then tune.
5. **Earnings guard** (`docs/known-limitations.md`): SOFI earnings during contract life can blow spreads. v2 ticket.

## Conclusion

**PASS**

All review findings addressed with test coverage. The two real-money correctness bugs (partial-loss mis-accounting, stuck-position-when-BP-low) are fixed and regression-tested. The change is safe to archive once the operator runs the paper smoke (task 10.3) to validate Alpaca's API accepts the MLEG order shape we construct.

Recommended next step: operator runs the paper smoke, then `/sdd-archive low-capital-wheel`.
