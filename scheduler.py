"""
Unified async scheduler. Runs three bots concurrently:

  trailing_task  — WebSocket price stream (always on)
  copy_task      — Capitol Trades polling every 4h
  wheel_task     — Wheel strategy every 15min during market hours
  summary_task   — Daily summary at market close
"""
import asyncio
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from shared import market_hours
from shared import trader as shared_trader
import trailing.state   as trailing_state
import trailing.strategy as trailing_strategy
import trailing.stream   as trailing_stream
import copy.state   as copy_state_mod
import copy.scraper as scraper
import copy.scorer  as scorer
import copy.copier  as copier
import copy.portfolio as portfolio
import wheel.state   as wheel_state_mod
import wheel.engine  as wheel_engine
import wheel.monitor as wheel_monitor
import wheel.summary as wheel_summary

TSLA = "TSLA"
INITIAL_QTY = 20


# ── Trailing Stop ──────────────────────────────────────────────────────────

async def trailing_task():
    s = trailing_state.load()
    if s is None:
        print(f"[TRAILING] No state. Buying {INITIAL_QTY} {TSLA}")
        shared_trader.buy(TSLA, INITIAL_QTY)
        entry = shared_trader.get_latest_price(TSLA)
        s = {
            "symbol": TSLA, "entry_price": entry,
            "position_qty": INITIAL_QTY,
            "floor": round(entry * 0.90, 2),
            "trailing_active": False, "high_watermark": entry,
            "ladder_15_done": False, "ladder_22_done": False,
            "ladder_30_done": False, "ladder_40_done": False,
        }
        trailing_state.save(s)
        _print_trailing_summary(s)
    else:
        print(f"[TRAILING] Resuming: entry=${s['entry_price']} floor=${s['floor']}")

    async def on_price(price: float):
        current = trailing_state.load()
        if current is None:
            return
        actions = trailing_strategy.evaluate(price, current)
        for action in actions:
            print(f"[TRAILING] {action.type.upper()} qty={action.qty} | {action.reason}")
            if action.type == "buy":
                shared_trader.buy(TSLA, action.qty)
                current["position_qty"] += action.qty
            elif action.type == "sell":
                shared_trader.sell(TSLA, action.qty)
                trailing_state.clear()
                return
        trailing_state.save(current)

    # run in executor to not block the event loop
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, trailing_stream.start, TSLA, on_price)


# ── Copy Trader ────────────────────────────────────────────────────────────

async def copy_task():
    INTERVAL = 4 * 3600  # 4 hours
    SCORE_INTERVAL = 24 * 3600  # re-score every 24h

    while True:
        state = copy_state_mod.load()
        now_str = datetime.utcnow().isoformat()

        # Re-score politician every 24h
        last_scored = state.get("last_scored")
        needs_rescore = (
            last_scored is None or
            (datetime.utcnow() - datetime.fromisoformat(last_scored)).total_seconds() > SCORE_INTERVAL
        )

        print("[COPY] Fetching Capitol Trades...")
        try:
            # fetch_trades is sync (httpx.Client) — run in thread pool
            loop = asyncio.get_running_loop()
            trades = await loop.run_in_executor(None, scraper.fetch_trades, 3)
        except Exception as e:
            print(f"[COPY] Scraper error: {e}")
            await asyncio.sleep(INTERVAL)
            continue

        if needs_rescore:
            top = scorer.score_and_pick(trades)
            if top:
                state["following"] = top
                state["last_scored"] = now_str
                print(f"[COPY] Now following: {top}")

        following = state.get("following")
        if not following:
            await asyncio.sleep(INTERVAL)
            continue

        new_trades = copier.new_trades_to_copy(trades, following, state["seen_trade_ids"])
        for t in new_trades:
            portfolio.execute_new_trade(t, state)
            state["seen_trade_ids"].append(t["id"])

        copy_state_mod.save(state)
        await asyncio.sleep(INTERVAL)


# ── Wheel Strategy ──────────────────────────────────────────────────────────

async def wheel_task():
    MONITOR_INTERVAL = 15 * 60  # 15 minutes

    while True:
        if not market_hours.is_market_open():
            await asyncio.sleep(60)
            continue

        state = wheel_state_mod.load()

        # 50% profit check first
        state = wheel_monitor.check_early_close(state)
        # Main engine cycle
        state = wheel_engine.run_cycle(state)

        wheel_state_mod.save(state)

        # Daily summary at market close
        if market_hours.is_market_close():
            wheel_summary.print_summary(state)

        await asyncio.sleep(MONITOR_INTERVAL)


def _print_trailing_summary(s: dict):
    e = s["entry_price"]
    print(f"[TRAILING] Entry=${e:.2f} | Floor=${s['floor']:.2f} | "
          f"Ladder: -15%=${e*0.85:.2f} -22%=${e*0.78:.2f} "
          f"-30%=${e*0.70:.2f} -40%=${e*0.60:.2f}")
