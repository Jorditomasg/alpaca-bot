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
import copy_trader.state   as copy_state_mod
import copy_trader.scraper as scraper
import copy_trader.scorer  as scorer
import copy_trader.copier  as copier
import copy_trader.portfolio as portfolio
import wheel.state   as wheel_state_mod
import wheel.engine  as wheel_engine
import wheel.monitor as wheel_monitor
import wheel.summary as wheel_summary

TSLA = "TSLA"
INITIAL_ALLOCATION = 0.30  # Spend 30% of buying power initially


# ── Trailing Stop ──────────────────────────────────────────────────────────

async def trailing_task():
    s = trailing_state.load()
    if s is None:
        print("[TRAILING] No state. Searching for consensus stock...")
        try:
            # Run scraper in thread pool to avoid blocking
            loop = asyncio.get_running_loop()
            trades = await loop.run_in_executor(None, scraper.fetch_trades)
            ticker = scorer.get_consensus_ticker(trades) or "TSLA" # Fallback to TSLA
        except Exception as e:
            print(f"[TRAILING] Could not find consensus stock: {e}")
            ticker = "TSLA"

        bp = shared_trader.get_buying_power()
        budget = round(bp * INITIAL_ALLOCATION, 2)
        print(f"[TRAILING] Top Consensus Stock: {ticker}. Buying ${budget}")
        
        try:
            shared_trader.buy(ticker, notional=budget)
            entry = shared_trader.get_latest_price(ticker)
            qty = round(budget / entry, 4)
            
            s = {
                "symbol": ticker, "entry_price": entry,
                "position_qty": qty,
                "floor": round(entry * 0.90, 2),
                "trailing_active": False, "high_watermark": entry,
                "ladder_15_done": False, "ladder_22_done": False,
                "ladder_30_done": False, "ladder_40_done": False,
            }
            trailing_state.save(s)
            _print_trailing_summary(s)
        except Exception as e:
            print(f"[TRAILING] Initial buy failed for {ticker}: {e}")
            return
    else:
        ticker = s["symbol"]
        print(f"[TRAILING] Resuming {ticker}: entry=${s['entry_price']} floor=${s['floor']}")

    async def on_price(price: float):
        current = trailing_state.load()
        if current is None:
            return
        
        symbol = current["symbol"]
        actions = trailing_strategy.evaluate(price, current)
        for action in actions:
            print(f"[TRAILING] {action.type.upper()} | {action.reason}")
            try:
                if action.type == "buy":
                    shared_trader.buy(symbol, notional=action.notional)
                    added_qty = action.notional / price
                    current["position_qty"] += round(added_qty, 4)
                elif action.type == "sell":
                    shared_trader.sell(symbol, qty=current["position_qty"])
                    trailing_state.clear()
                    # After selling, task will loop and find a NEW consensus stock next cycle
                    return
            except Exception as e:
                print(f"[TRAILING] Action {action.type} failed: {e}")
        
        trailing_state.save(current)

    # run in executor to not block the event loop
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, trailing_stream.start, ticker, on_price)


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
            trades = await loop.run_in_executor(None, scraper.fetch_trades)
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
        if new_trades:
            portfolio.execute_batch(new_trades, state)
            for t in new_trades:
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
