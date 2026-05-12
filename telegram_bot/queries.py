"""Read-only formatters used by /status, /positions, /pnl commands.

Wraps each Alpaca call in try/except — never raises into the poller.
"""
import asyncio
from shared import alpaca_client
import trailing.state as trailing_state
import copy_trader.state as copy_state
import wheel.state as wheel_state


async def format_status() -> str:
    """Snapshot all three strategies. Sync state reads run in executor."""
    loop = asyncio.get_running_loop()
    t = await loop.run_in_executor(None, trailing_state.load)
    c = await loop.run_in_executor(None, copy_state.load)
    w = await loop.run_in_executor(None, wheel_state.load)

    lines = ["*Status*"]
    if t:
        active = "active" if t.get("trailing_active") else "armed"
        lines.append(
            f"Trailing {t['symbol']}: {t['position_qty']:.4f} sh @ "
            f"\\${t['entry_price']:.2f}, floor \\${t['floor']:.2f} ({active})"
        )
    else:
        lines.append("Trailing: no state (idle)")
    if c and c.get("following"):
        n = len((c.get("positions") or {}))
        lines.append(f"Copy: following {c['following']}, {n} open")
    else:
        lines.append("Copy: no politician selected")
    if w:
        lines.append(f"Wheel {w.get('symbol','?')}: stage {w.get('stage','?')}")
    else:
        lines.append("Wheel: no state")
    return "\n".join(lines)


async def format_positions() -> str:
    """List open positions from Alpaca with unrealized PnL %."""
    loop = asyncio.get_running_loop()
    try:
        client = alpaca_client.trading()
        positions = await loop.run_in_executor(None, client.get_all_positions)
    except Exception as e:
        return f"Could not fetch positions: {e}"
    if not positions:
        return "No open positions."
    lines = ["*Open positions*"]
    for p in positions:
        try:
            sym = p.symbol
            qty = float(p.qty)
            entry = float(p.avg_entry_price)
            cur = float(p.current_price)
            pct = (cur - entry) / entry * 100 if entry else 0.0
            sign = "+" if pct >= 0 else ""
            lines.append(f"{sym} {qty:.4f} @ \\${entry:.2f} → \\${cur:.2f} ({sign}{pct:.2f}%)")
        except Exception:
            continue
    return "\n".join(lines)


async def format_pnl() -> str:
    loop = asyncio.get_running_loop()
    try:
        client = alpaca_client.trading()
        acct = await loop.run_in_executor(None, client.get_account)
        equity = float(acct.equity)
        last = float(acct.last_equity)
        bp = float(acct.buying_power)
        day_pct = (equity - last) / last * 100 if last else 0.0
        sign = "+" if day_pct >= 0 else ""
        return (f"*PnL*\n"
                f"Equity: \\${equity:,.2f}\n"
                f"Day: {sign}{day_pct:.1f}% (was \\${last:,.2f})\n"
                f"Buying power: \\${bp:,.2f}")
    except Exception as e:
        return f"Could not fetch account: {e}"
