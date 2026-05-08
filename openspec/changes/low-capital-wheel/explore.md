# Exploration: low-capital-wheel

## Problem Framing

The wheel strategy cannot execute with $1,000 because of three hardcoded constraints:

1. `wheel/state.py:14` — default symbol is `"TSLA"` (price ~$385)
2. `wheel/engine.py:51-53` — capital check: `required_cash = contract["strike"] * 100`. TSLA at 10%-OTM → `$346 × 100 = $34,600` required. The guard correctly refuses, but the strategy never runs.
3. `wheel/options.py:49-50` — strike window `±$5` is sensible for TSLA but wrong for $5-$10 stocks (where strikes may be $0.50-$1 apart).

Additionally, `scheduler.py:29` declares `TSLA = "TSLA"` as a module-level constant, reinforcing TSLA as the de-facto only symbol. No multi-leg order support exists. No tests exist.

## Affected Areas

- `wheel/state.py` — symbol hardcode, missing spread state fields
- `wheel/options.py` — single-leg only, narrow strike window
- `wheel/engine.py` — state machine has no spread transitions
- `wheel/monitor.py` — 50% profit logic correct but only for single-leg
- `wheel/summary.py` — no spread-specific metrics reported
- `scheduler.py:29` — TSLA constant, silent failure on insufficient capital

## Approaches

### 1. Cheap Underlyings Classic Wheel (CSP on SOFI/F)
- Capital required: $810-$1,000 for a single CSP (SOFI at $9-$10)
- Expected yield: $20-$40/month (2-4% on collateral)
- Critical flaw: one assignment consumes the ENTIRE account → wheel becomes a stock trap
- Effort: LOW
- Verdict: Technically works once, breaks after any assignment

### 2. Bull Put Spread — RECOMMENDED
- Capital required: $200-$500 per spread (configurable width)
- Expected yield: $80-$120/month on $1,000 committed (8-12%)
- Risk profile: defined. Max loss = `(width × 100) - credit`. No assignment possible.
- Alpaca paper support: CONFIRMED. Level 3 auto-enabled since February 2025. `order_class=OrderClass.MLEG` + `OptionLegRequest` is the SDK pattern.
- Effort: MEDIUM. New `wheel/spreads.py`, modified engine state machine (simpler: no ASSIGNED/CALL_OPEN states).
- Verdict: STRONG. Best capital efficiency, defined risk, works on liquid cheap underlyings.

### 3. Iron Condor
- Capital: $500/condor. Two condors = $1,000. Manageable but tight.
- 4-leg order complexity + two-sided monitoring = too much complexity for this codebase's maturity.
- Verdict: DEFERRED to v2 at higher capital.

### 4. Poor Man's Covered Call (PMCC)
- Capital: ~$400 for SOFI LEAPS. Yield: ~$25/month = 6.25% annualized on LEAPS.
- Lower yield than bull put spread, higher complexity (LEAPS decay, rolling).
- Verdict: NOT RECOMMENDED at this stage.

### 5. Synthetic Wheel (put + call credit spreads, two-phase)
- Long-term v2 target: full wheel mimicry with defined risk.
- Too complex for first pass.
- Verdict: v2 after Option 2 is proven.

### 6. Micro-options (XSP, MES)
- Not available on Alpaca. BLOCKED.

### 7. Disable Wheel (null option)
- NECESSARY as fallback. Add a clear capital guard with minimum threshold log message.
- Not a real solution alone.

## Approaches Table

| Approach | Capital | Monthly Yield | Complexity | Assignment Risk | Alpaca Support | Verdict |
|----------|---------|---------------|------------|-----------------|----------------|---------|
| CSP cheap underlying | $810-$1,000 | 2-4% | LOW | HIGH (account freeze) | YES (Level 1) | Marginal |
| Bull Put Spread | $200-$500 | 8-12% | MEDIUM | NONE | YES (Level 3, paper auto) | RECOMMENDED |
| Iron Condor | $500 | 5-8% | HIGH | NONE | YES (Level 3) | Deferred |
| PMCC | $400 | 5-7% | MEDIUM-HIGH | NONE | Unclear | Skip |
| Synthetic Wheel | $200-$500 | 10-15% | HIGH | NONE | YES (Level 3) | v2 target |
| Micro-options | N/A | N/A | N/A | N/A | NOT AVAILABLE | Blocked |
| Disable | $0 | 0% | TRIVIAL | NONE | N/A | Fallback only |

## Recommendation

**Implement bull put spreads on SOFI as the primary strategy.** Replace the CSP-only state machine in `wheel/engine.py` with a spread-aware engine. The state machine SIMPLIFIES: remove the `ASSIGNED` and `CALL_OPEN` states (no stock delivery possible). New flow: `IDLE → SPREAD_OPEN → IDLE`. Keep the old CSP path gated by a `strategy_type` config key for backward compatibility (CSP still useful when capital grows).

New module `wheel/spreads.py` handles multi-leg order construction using `OptionLegRequest` from alpaca-py. The 50%-profit monitor in `wheel/monitor.py` applies unchanged (same logic, different contract reference). Symbol defaults to `"SOFI"` — move hardcode from `state.py:14` to an explicit config field.

For the test environment, bootstrap `pytest + pytest-mock + pytest-asyncio` in `sdd-apply` and build three layers:

1. **Unit tests** (mocked Alpaca clients) — fast, runnable offline, cover all state transitions and contract selection logic
2. **Replay tests** (fixture JSON snapshots of real option chains) — validate P&L behavior of the strategy over captured market data
3. **Integration tests** (real paper account) — marked `@pytest.mark.integration`, skipped in CI, validate Alpaca API accepts mleg spread orders

## Open Questions for Proposal Phase

1. **Spread width**: $2-wide or $5-wide? On a $9-$10 stock, $5-wide strikes may not exist. Need to verify SOFI chain structure. This dictates max contracts per $1K ($200 collateral per $2-wide = up to 5 contracts vs $500 per $5-wide = up to 2 contracts).
2. **Symbol auto-selection**: Should the wheel auto-screen symbols (like trailing/copy_trader do) or require explicit config? Recommendation: explicit config first, auto-screen as v2.
3. **PMCC "assignment mimic" for v2**: Once bull put spread goes to max loss, should we optionally enter a PMCC to continue the wheel? Complex — defer.
4. **Capital guard threshold**: Suggest `spread_width × 100 × 2` as minimum (2 contracts). At $2-wide: $400 minimum.
5. **Fixture collection script**: Needed to build replay tests. In scope for sdd-apply or pre-task?

## Risks

- Alpaca paper option chain data for SOFI may have stale quotes outside market hours — spread mid-price calculation needs BOTH legs valid simultaneously
- $2-wide spread strikes may not always exist at exactly 10%-OTM target — `_find_contract` strike window logic in `options.py` needs revisiting
- Level 3 is auto-enabled in paper but requires manual upgrade request for live accounts — deployment story changes when moving to live
- No test infrastructure exists today — pytest bootstrap must be a prerequisite task before any test-writing tasks

## Sources

- [Multi-Leg (Level 3) Options Trading at Alpaca](https://alpaca.markets/blog/level-3-options-trading-now-available-with-alpacas-trading-api/)
- [Options Level 3 Trading — Alpaca Docs](https://docs.alpaca.markets/docs/options-level-3-trading)
- [alpaca-py Iron Condor Example](https://github.com/alpacahq/alpaca-py/blob/master/examples/options/options-iron-condor.ipynb)
- [Best Stocks for the Wheel Strategy 2026](https://options.cafe/blog/best-stocks-for-wheel-strategy/)
- [Poor Man's Covered Call Guide](https://www.daystoexpiry.com/blog/poor-mans-covered-call)
