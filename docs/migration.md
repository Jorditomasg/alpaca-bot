# Migration Guide: CSP to Bull Put Spread

## Overview

The wheel strategy now defaults to `bull_put_spread` mode. Existing installations
running the legacy Cash-Secured Put (CSP) strategy will be migrated automatically
on the next startup.

## What happens on first startup after upgrade

1. If `data/wheel_state.json` exists WITHOUT a `strategy_type` field:
   - The engine detects it as a legacy CSP state file
   - `strategy_type` is automatically set to `"csp"`
   - A one-time banner is printed: `[WHEEL] Legacy state detected → strategy_type defaulted to 'csp'`
   - The existing CSP cycle (PUT_OPEN, ASSIGNED, or CALL_OPEN) continues uninterrupted
   - **No open positions are affected**

2. If no state file exists: a fresh `bull_put_spread` state is created.

## Switching to bull_put_spread after a CSP cycle

The safest migration path:

1. **Wait for the current CSP cycle to complete** (return to `IDLE` stage).
2. Delete or rename the state file:
   ```bash
   mv data/wheel_state.json data/wheel_state.json.bak
   ```
3. Set the new strategy env vars:
   ```bash
   export WHEEL_STRATEGY_TYPE=bull_put_spread
   export WHEEL_SYMBOL=SOFI
   ```
4. Restart the bot. A fresh spread-mode state will be created.

## Manually editing the state file

If you need to switch mid-cycle (not recommended):

```json
{
  "strategy_type": "bull_put_spread",
  "stage": "IDLE",
  "symbol": "SOFI",
  "cycles": 0,
  "total_premium": 0.0,
  "premium_received": 0.0,
  "contract_symbol": null,
  "contract_strike": null,
  "contract_expiry": null,
  "cost_basis": null,
  "shares_owned": 0,
  "short_symbol": null,
  "short_strike": null,
  "long_symbol": null,
  "long_strike": null,
  "net_credit": 0.0,
  "max_loss": 0.0,
  "spread_width": 2.0,
  "last_logged_insufficient_at": null
}
```

WARNING: If you have an open CSP position (PUT_OPEN / ASSIGNED / CALL_OPEN),
switching manually WILL orphan that position. The engine will not track it.
Always let the CSP cycle close naturally before switching.
