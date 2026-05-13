# Alpaca Bot — Project Rules

This is a paper-trading bot running three independent strategies (trailing,
copy, wheel) over a single Alpaca account. Real (or paper) money is at risk on
every change. The following rules are MANDATORY.

## 1. Profitability gate — backtest before changing trading logic

**Any change that touches entry, exit, scoring, sizing, or filter logic in
`copy_trader/`, `trailing/`, `wheel/`, or `scheduler.py` MUST be validated with
a backtest before being merged.**

The flow is non-negotiable:

1. **Define hypothesis** — one sentence: "this change should improve X metric
   by ~Y, at most -Z cost on another metric." If you cannot state this, you do
   not understand the change well enough to ship it.
2. **Run baseline** — checkout current `main`, run the relevant backtest, save
   the metrics table (return, CAGR, max drawdown, Sharpe, win rate, avg
   holding days).
3. **Apply change behind a config flag or as a new strategy variant** — never
   replace baseline logic in-place until the variant proves out.
4. **Run improved variant** on the same data window with the same starting
   capital, same politician/symbol/etc. Compare to baseline.
5. **Accept-or-reject criteria:**
   - Improved Sharpe ≥ baseline Sharpe (risk-adjusted return must not regress)
   - Improved max drawdown ≤ user's tolerance (currently -10% absolute)
   - Total return delta and the reasoning behind any regression documented
6. **Only then merge** — and include the metrics comparison in the commit
   message or PR description.

The backtest harness lives in `backtest/`:

```bash
.venv/bin/python -m backtest.runner \
    --start 2018-01-01 --end 2020-12-31 \
    --cash 100000 --notional 5000 \
    --min-amount 5000 --max-holding 180 --freshness-days 30
```

Defaults match the validated config from the original sweep (improved variant
beat baseline on Sharpe in 2/3 politicians tested, with 5-8× drawdown
reduction). Anything that beats those numbers on the same window is a real
improvement; anything that doesn't is at best lateral and needs justification.

**Data caveats:**

- Senate Stock Watcher data ends 2020-12-02. The backtest covers COVID-era
  only. For live-money decisions, repeat the backtest on a fresher dataset
  (paid API or direct scrape of `efdsearch.senate.gov`).
- `backtest/data/senate_all.json` and `backtest/data/price_cache/` are
  gitignored. Run:
  ```bash
  mkdir -p backtest/data
  curl -sL https://raw.githubusercontent.com/timothycarambat/senate-stock-watcher-data/master/aggregate/all_transactions.json \
       -o backtest/data/senate_all.json
  ```
- First backtest run hits Alpaca for ~hundreds of tickers (10-15 minutes).
  Subsequent runs are seconds because of the on-disk price cache.

## 2. TDD for any logic change

Every trading-logic change goes through red → green → refactor. No exceptions.

- Write the failing test first. It must describe the new behavior in domain
  terms (e.g., `test_seed_seen_ids_marks_all_visible_trades_of_new_following`),
  not implementation terms.
- Make it pass with the minimal change.
- Refactor only on green.

Existing test layout: `tests/unit/test_<module>.py` matching `<module>` under
the corresponding package. Run the full suite before committing:

```bash
.venv/bin/python -m pytest
```

255+ tests pass on `main`. Any new change that drops the count is suspect.

## 3. Scope discipline

- Bug fixes do NOT bundle unrelated refactors.
- Profitability changes do NOT bundle infrastructure work.
- One concern per PR, even if it produces small diffs.

The goal is that any single change can be reverted in isolation without
collateral damage.

## 4. Position-level safety

- Every new position must be stamped with `entry_date`, `cost_basis`,
  `high_watermark` at open time so the exits module can evaluate stop/
  trail/max-holding rules later. See `copy_trader/portfolio.py:_stamp_open`.
- Positions missing this metadata are silently SKIPPED by exits — this is by
  design (no false stops from legacy state), but means a manual migration is
  needed when changing the schema. Document the migration in the PR.

## 5. Capital allocation awareness

All three strategies share one Alpaca buying-power pool. A change that lets
one strategy consume more aggressively must be justified against the others'
needs. The wheel strategy needs $400+ for spreads or $40k+ for CSP. The
trailing strategy needs ~30% of buying power for the initial entry plus ladder
buys. The copy strategy rebalances across N filtered positions.

Currently the paper account is ~$1000. If the change shifts allocation, run
the full pipeline (not just backtest) in paper for at least one trading day
before merging.

## 6. No production data in commits

`.gitignore` already protects this: `*.json` is gitignored except
`tests/fixtures/**/*.json` (which is whitelisted for committed test fixtures).
If you add a new state file or data dump, verify it's covered before staging.
