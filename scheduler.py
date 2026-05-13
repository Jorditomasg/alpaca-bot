"""
Unified async scheduler. Runs bots concurrently:

  trailing_task        — WebSocket price stream (always on)
  copy_task            — Capitol Trades polling every 4h
  wheel_task           — Wheel strategy every 15min during market hours
  daily_summary_task   — Daily summary at market close (once per day)
"""
import asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()

import shared
from shared import market_hours
from shared import trader as shared_trader
import shared.control as control
import shared.kill_switch as kill_switch
import trailing.state   as trailing_state
import trailing.strategy as trailing_strategy
import trailing.stream   as trailing_stream
import trailing.atr      as trailing_atr
import copy_trader.state   as copy_state_mod
import copy_trader.scraper as scraper
import copy_trader.scorer  as scorer
import copy_trader.copier  as copier
import copy_trader.portfolio as portfolio
import copy_trader.exits  as copy_exits
import copy_trader.config as copy_config
import wheel.state   as wheel_state_mod
import wheel.engine  as wheel_engine
import wheel.monitor as wheel_monitor
import wheel.summary as wheel_summary
from telegram_bot import notifier as tg_notifier
from telegram_bot import client as tg_client
from telegram_bot.formatter import html_escape

import os

INITIAL_ALLOCATION = 0.30
ATR_MULTIPLIER = float(os.getenv("TRAILING_ATR_MULTIPLIER", "2.5"))


# ── Trailing Stop ──────────────────────────────────────────────────────────

def _refresh_kill_switch() -> bool:
    """Update kill-switch with current equity; return True if halted.

    Logs at most once per call. Safe to invoke before any new-position decision.
    """
    try:
        equity = shared_trader.get_equity()
    except Exception as e:
        print(f"[KILL-SWITCH] Equity fetch failed: {e}")
        return False  # fail open
    ks_state = kill_switch.update(equity)
    kill_switch.save(ks_state)
    if ks_state.get("halted"):
        print(f"[KILL-SWITCH] HALT active — {ks_state.get('halt_reason')}")
        return True
    return False


async def trailing_task():
    s = trailing_state.load()
    if s is None:
        if _refresh_kill_switch():
            print("[TRAILING] Kill switch active — skipping initial entry.")
            return
        print("[TRAILING] No state. Searching for consensus stock...")
        try:
            loop = asyncio.get_running_loop()
            trades = await loop.run_in_executor(None, scraper.fetch_trades)
            ticker = scorer.get_consensus_ticker(trades) or "TSLA"
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
                "atr": None, "atr_refreshed_at": None,
                "atr_multiplier": ATR_MULTIPLIER,
            }
            # Best-effort ATR seed on entry; refreshes in on_price if it fails now.
            try:
                bars = await loop.run_in_executor(
                    None, shared_trader.get_recent_bars, ticker, 30
                )
                trailing_atr.refresh_atr_in_state(
                    s, fetch_bars=lambda _: bars,
                )
                if s.get("atr"):
                    print(f"[TRAILING] ATR seeded: {s['atr']} (k={ATR_MULTIPLIER})")
            except Exception as e:
                print(f"[TRAILING] ATR seed failed (will retry on next tick): {e}")

            trailing_state.save(s)
            _print_trailing_summary(s)
            await tg_notifier.notify_trade(
                strategy="trailing", side="buy", symbol=ticker,
                notional=budget, price=entry, reason="Initial entry",
            )
        except Exception as e:
            print(f"[TRAILING] Initial buy failed for {ticker}: {e}")
            await tg_notifier.notify_error("trailing_task", f"Initial buy failed: {e}")
            return
    else:
        ticker = s["symbol"]
        print(f"[TRAILING] Resuming {ticker}: entry=${s['entry_price']} floor=${s['floor']}")

    async def on_price(price: float):
        current = trailing_state.load()
        if current is None:
            return

        if control.flags.is_paused("trailing"):
            return

        symbol = current["symbol"]

        # Lazy ATR refresh: only fetch bars when the cache is stale or empty.
        # Avoids hitting the data API on every tick.
        now_ts = datetime.now(timezone.utc).timestamp()
        last_atr_ts = current.get("atr_refreshed_at") or 0
        atr_stale = (
            current.get("atr") is None
            or (now_ts - last_atr_ts) >= trailing_atr.DEFAULT_REFRESH_SECONDS
        )
        if atr_stale:
            try:
                inner_loop = asyncio.get_running_loop()
                bars = await inner_loop.run_in_executor(
                    None, shared_trader.get_recent_bars, symbol, 30
                )
                trailing_atr.refresh_atr_in_state(
                    current, fetch_bars=lambda _: bars, now=now_ts,
                )
            except Exception:
                pass  # ATR is advisory; strategy falls back to fixed-% trail

        prev_active = current.get("trailing_active", False)
        actions = trailing_strategy.evaluate(price, current)

        if not prev_active and current.get("trailing_active") and not current.get("_trailing_active_notified"):
            await tg_notifier.notify_state(
                "trailing", "trailing_active",
                {"floor": current["floor"], "symbol": symbol},
            )
            current["_trailing_active_notified"] = True

        for action in actions:
            # Block ladder buys when kill switch is active. Exits always allowed.
            if action.type == "buy" and _refresh_kill_switch():
                print(f"[TRAILING] Kill switch active — skipping ladder buy ({action.reason})")
                continue
            print(f"[TRAILING] {action.type.upper()} | {action.reason}")
            try:
                if action.type == "buy":
                    shared_trader.buy(symbol, notional=action.notional)
                    added_qty = action.notional / price
                    current["position_qty"] += round(added_qty, 4)
                    await tg_notifier.notify_trade(
                        strategy="trailing", side="buy", symbol=symbol,
                        notional=action.notional, price=price, reason=action.reason,
                    )
                elif action.type == "sell":
                    # Use close_position (atomic full exit) — avoids the
                    # fractional drift between locally-tracked qty and the
                    # broker's actual qty after a series of notional buys.
                    shared_trader.close_position(symbol)
                    await tg_notifier.notify_trade(
                        strategy="trailing", side="sell", symbol=symbol,
                        qty=current["position_qty"], price=price, reason=action.reason,
                    )
                    trailing_state.clear()
                    return
            except Exception as e:
                print(f"[TRAILING] Action {action.type} failed: {e}")
                await tg_notifier.notify_error("trailing_task", f"{action.type} failed: {e}")

        trailing_state.save(current)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, trailing_stream.start, ticker, on_price)


# ── Copy Trader ────────────────────────────────────────────────────────────

async def copy_task():
    INTERVAL = 4 * 3600
    SCORE_INTERVAL = 24 * 3600
    consec_scrape_fail = 0

    while True:
        await control.flags.wait_if_paused("copy")
        state = copy_state_mod.load()
        now_str = datetime.utcnow().isoformat()

        last_scored = state.get("last_scored")
        needs_rescore = (
            last_scored is None or
            (datetime.utcnow() - datetime.fromisoformat(last_scored)).total_seconds() > SCORE_INTERVAL
        )

        print("[COPY] Fetching Capitol Trades...")
        try:
            loop = asyncio.get_running_loop()
            trades = await loop.run_in_executor(None, scraper.fetch_trades)
            consec_scrape_fail = 0
        except Exception as e:
            consec_scrape_fail += 1
            print(f"[COPY] Scraper error: {e}")
            if consec_scrape_fail == 3:
                await tg_notifier.notify_warn("COPY", "Scraper failing — 3 consecutive errors")
            await asyncio.sleep(INTERVAL)
            continue

        if needs_rescore:
            top = scorer.score_and_pick(trades)
            if top and top != state.get("following"):
                old = state.get("following")
                state["following"] = top
                state["last_scored"] = now_str
                # Seed visible history so we copy only NEW trades after the switch.
                # Otherwise the politician's already-published portfolio drains
                # buying power on the first poll.
                copier.seed_seen_ids_for(state, trades, top)
                scores = scorer.score_all_politicians(trades)
                await tg_notifier.notify_state(
                    "copy", "follow_change",
                    {"politician": top, "score": scores.get(top, 0.0)},
                )
                print(f"[COPY] Now following: {top} (was {old})")

        following = state.get("following")
        if not following:
            await asyncio.sleep(INTERVAL)
            continue

        # Per-position exit checks BEFORE entering new trades. Frees capital that
        # rebalance would otherwise dilute across stale positions.
        await _run_copy_exits(state)

        today_iso = datetime.utcnow().strftime("%Y-%m-%d")
        new_trades = copier.new_trades_to_copy(
            trades, following, state["seen_trade_ids"],
            today=today_iso,
            freshness_days=copy_config.PUB_FRESHNESS_DAYS,
            min_amount=copy_config.MIN_AMOUNT,
        )
        if new_trades:
            try:
                portfolio.execute_batch(new_trades, state)
                tickers = ", ".join(t["ticker"] for t in new_trades[:5])
                more = "" if len(new_trades) <= 5 else f" (+{len(new_trades)-5} more)"
                await tg_client.send_message(
                    f"<b>[COPY]</b> Executed {len(new_trades)} trades: "
                    f"{html_escape(tickers)}{html_escape(more)}"
                )
            except Exception as e:
                print(f"[COPY] Batch execution failed: {e}")
                await tg_notifier.notify_error("copy_task", str(e))
            for t in new_trades:
                state["seen_trade_ids"].append(t["id"])

        copy_state_mod.save(state)
        await asyncio.sleep(INTERVAL)


async def _run_copy_exits(state: dict) -> None:
    """Evaluate stop / trailing / max-holding exits on each cycle.

    Fetches current prices for held positions, asks the exits module which to
    close, and forwards each decision to the broker via portfolio.close_and_remove.
    """
    positions = state.get("positions") or {}
    if not positions:
        return

    loop = asyncio.get_running_loop()
    prices: dict[str, float] = {}
    for ticker in list(positions.keys()):
        try:
            price = await loop.run_in_executor(None, shared_trader.get_latest_price, ticker)
            prices[ticker] = price
        except Exception as e:
            print(f"[COPY] price fetch failed for {ticker}: {e}")

    today_iso = datetime.utcnow().strftime("%Y-%m-%d")
    decisions = copy_exits.evaluate(
        positions, prices,
        today=today_iso,
        stop_loss_pct=copy_config.STOP_LOSS_PCT,
        trail_arm_pct=copy_config.TRAIL_ARM_PCT,
        trail_giveback_pct=copy_config.TRAIL_GIVEBACK_PCT,
        max_holding_days=copy_config.MAX_HOLDING_DAYS,
    )
    for d in decisions:
        print(f"[COPY] EXIT {d.ticker} | {d.reason}")
        try:
            await loop.run_in_executor(None, portfolio.close_and_remove, d.ticker, state)
            await tg_notifier.notify_state(
                "copy", "exit",
                {"ticker": d.ticker, "reason": d.reason},
            )
        except Exception as e:
            print(f"[COPY] EXIT {d.ticker} failed: {e}")
            await tg_notifier.notify_error("copy_exits", f"{d.ticker}: {e}")


# ── Wheel Strategy ──────────────────────────────────────────────────────────

async def wheel_task():
    MONITOR_INTERVAL = 15 * 60

    while True:
        await control.flags.wait_if_paused("wheel")
        if not market_hours.is_market_open():
            await asyncio.sleep(60)
            continue

        try:
            state = wheel_state_mod.load()
            prev_stage = state.get("stage")

            state = wheel_monitor.check_early_close(state)
            state = wheel_engine.run_cycle(state)

            new_stage = state.get("stage")

            if prev_stage != "SPREAD_OPEN" and new_stage == "SPREAD_OPEN":
                await tg_notifier.notify_state("wheel", "spread_opened", {
                    "symbol": state.get("symbol", "?"),
                    "short_strike": state.get("short_strike", 0.0),
                    "long_strike": state.get("long_strike", 0.0),
                    "credit": state.get("net_credit", 0.0),
                })
            if prev_stage == "SPREAD_OPEN" and new_stage == "IDLE":
                pnl = state.get("realized_pnl", 0.0)
                credit = state.get("net_credit", 0.0) or 1.0
                pct = (pnl / credit * 100) if credit else 0.0
                await tg_notifier.notify_state("wheel", "spread_closed", {
                    "profit_pct": pct, "pnl": pnl,
                })

            wheel_state_mod.save(state)

            if market_hours.is_market_close():
                wheel_summary.print_summary(state)

        except Exception as e:
            print(f"[WHEEL] task error: {e}")
            await tg_notifier.notify_error("wheel_task", str(e))

        await asyncio.sleep(MONITOR_INTERVAL)


# ── Daily Summary ───────────────────────────────────────────────────────────

async def daily_summary_task():
    """Fires once per trading day at market close."""
    last_summary_date = None
    while True:
        try:
            now = market_hours.now_et()
            today = now.date()
            if market_hours.is_market_close() and last_summary_date != today:
                summary = await _build_daily_summary(today.isoformat())
                if summary:
                    await tg_notifier.notify_summary(**summary)
                last_summary_date = today
        except Exception as e:
            print(f"[SUMMARY] daily_summary_task error: {e}")
        await asyncio.sleep(60)


async def _build_daily_summary(date_str: str) -> dict | None:
    loop = asyncio.get_running_loop()
    t = await loop.run_in_executor(None, trailing_state.load)
    c = await loop.run_in_executor(None, copy_state_mod.load)
    w = await loop.run_in_executor(None, wheel_state_mod.load)

    trailing_block = None
    if t:
        try:
            price = shared_trader.get_latest_price(t["symbol"])
            entry = t["entry_price"]
            day_pct = (price - entry) / entry * 100 if entry else 0.0
        except Exception:
            day_pct = 0.0
        trailing_block = {
            "symbol": t["symbol"], "qty": t.get("position_qty", 0.0),
            "entry": t.get("entry_price", 0.0), "floor": t.get("floor", 0.0),
            "day_pct": day_pct,
        }

    copy_block = None
    if c:
        copy_block = {
            "following": c.get("following"),
            "open_count": len(c.get("positions") or {}),
            "day_pct": 0.0,
        }

    wheel_block = None
    if w:
        wheel_block = {
            "symbol": w.get("symbol", "?"),
            "stage": w.get("stage", "?"),
            "credit_week": w.get("total_premium", 0.0),
            "day_pct": 0.0,
        }

    account_block = None
    try:
        client = shared.alpaca_client.trading()
        acct = await loop.run_in_executor(None, client.get_account)
        equity = float(acct.equity)
        last = float(acct.last_equity)
        day_pct = (equity - last) / last * 100 if last else 0.0
        account_block = {
            "equity": equity, "day_pct": day_pct,
            "buying_power": float(acct.buying_power),
        }
    except Exception:
        pass

    return {
        "date_str": date_str,
        "trailing": trailing_block,
        "copy": copy_block,
        "wheel": wheel_block,
        "account": account_block,
    }


def _print_trailing_summary(s: dict):
    e = s["entry_price"]
    print(f"[TRAILING] Entry=${e:.2f} | Floor=${s['floor']:.2f} | "
          f"Ladder: -15%=${e*0.85:.2f} -22%=${e*0.78:.2f} "
          f"-30%=${e*0.70:.2f} -40%=${e*0.60:.2f}")
