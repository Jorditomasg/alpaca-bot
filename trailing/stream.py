"""Supervised Alpaca trade-price stream for the trailing-stop strategy.

The SDK's `StockDataStream.run()` reconnects internally, but with no backoff
and without releasing the previous session. On 2026-07-30 that turned a local
DNS blip into ~7,900 `socket.gaierror` tracebacks and 829 `ValueError:
connection limit exceeded` — Alpaca allows one concurrent data connection per
account, and the hot retry loop kept claiming a slot it had never given back.

The cost of that is not cosmetic: while the feed is down `on_price` never
fires, so the trailing stop stops trailing and the open position runs unbounded
until the stream recovers. This module wraps the SDK in a supervisor that
closes the dead stream, backs off exponentially, and rebuilds from scratch.
"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Awaitable, Callable
from alpaca.data.live import StockDataStream

INITIAL_BACKOFF = 5.0      # seconds before the first reconnect attempt
MAX_BACKOFF = 300.0        # ceiling — a 5-minute outage shouldn't spin
HEALTHY_RUN_SECONDS = 120.0  # a run at least this long clears the backoff


class StreamHandle:
    """Off switch for a running `start()` supervisor.

    `start()` blocks forever by design, which is right while a position is
    open and wrong the moment it closes: on 2026-08-15 the AMZN trailing stop
    fired, the state file was cleared, and the supervisor went on streaming
    AMZN for days into an `on_price` that returned immediately — holding
    Alpaca's one data connection for a strategy with nothing to manage.

    `stop()` is safe to call from another thread (the supervisor runs in an
    executor): it both flips the flag the supervisor loop checks and releases
    the live stream, which is what unblocks the in-flight `wss.run()`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stopped = False
        self._wss = None

    @property
    def stopped(self) -> bool:
        with self._lock:
            return self._stopped

    def stop(self) -> None:
        """Stop from a thread that is NOT the stream's own event loop."""
        with self._lock:
            self._stopped = True
            wss, self._wss = self._wss, None
        if wss is not None:
            _release(wss)

    async def astop(self) -> None:
        """Stop from *inside* the stream's event loop — e.g. from `on_price`.

        `StockDataStream.stop()` hops threads via
        `run_coroutine_threadsafe(...).result(timeout=5)`. Called from the loop
        it is trying to reach, that blocks the loop for the full timeout on
        every exit. `stop_ws()` just enqueues the stop message on the loop that
        is already running, so it returns immediately and `run()` unwinds
        normally.
        """
        with self._lock:
            self._stopped = True
            wss, self._wss = self._wss, None
        if wss is None:
            return
        stop_ws = getattr(wss, "stop_ws", None)
        if stop_ws is None:
            _release(wss)
            return
        try:
            await stop_ws()
        except Exception:
            _release(wss)

    def _bind(self, wss) -> None:
        """Register the stream the supervisor is about to block on.

        Binding after a `stop()` releases immediately — otherwise a stop that
        lands in the gap between factory call and `run()` would be lost.
        """
        with self._lock:
            if self._stopped:
                already_stopped = True
            else:
                already_stopped = False
                self._wss = wss
        if already_stopped:
            _release(wss)

    def _unbind(self) -> None:
        with self._lock:
            self._wss = None


def _new_stream() -> StockDataStream:
    return StockDataStream(
        os.environ["ALPACA_API_KEY"],
        os.environ["ALPACA_SECRET_KEY"],
    )


def _release(wss) -> None:
    """Hand the connection slot back. Best-effort: the stream is already dead,
    and an exception here would kill the supervisor that has to outlive it."""
    for method in ("stop", "close"):
        try:
            getattr(wss, method)()
            return
        except Exception:
            continue


def start(
    symbol: str,
    on_price: Callable[[float], Awaitable[None]],
    *,
    stream_factory: Callable[[], StockDataStream] = _new_stream,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    max_restarts: int | None = None,
    handle: StreamHandle | None = None,
) -> None:
    """Stream `symbol` trades into `on_price`, reconnecting until stopped.

    Blocks until `handle.stop()` is called (forever, when no handle is given).
    The injected `stream_factory`, `sleep`, `clock` and `max_restarts` exist so
    the reconnect policy is testable without a network or a wall-clock wait.
    """
    async def handler(data):
        await on_price(float(data.price))

    backoff = INITIAL_BACKOFF
    restarts = 0

    while True:
        if handle is not None and handle.stopped:
            return

        wss = stream_factory()
        if handle is not None:
            handle._bind(wss)
        started = clock()
        try:
            wss.subscribe_trades(handler, symbol)
            print(f"[TRAILING] Streaming {symbol} trades...")
            wss.run()
            print(f"[TRAILING] Stream for {symbol} ended.")
        except Exception as e:
            print(f"[TRAILING] Stream for {symbol} dropped: {type(e).__name__}: {e}")
        finally:
            if handle is not None:
                handle._unbind()
            _release(wss)

        # A stop that arrives mid-run must not be followed by a reconnect —
        # check before the backoff so we neither sleep nor rebuild.
        if handle is not None and handle.stopped:
            print(f"[TRAILING] Stream for {symbol} stopped — position closed.")
            return

        if max_restarts is not None and restarts >= max_restarts:
            return

        # A stream that held for a while hit a fresh problem, not an ongoing
        # outage — don't make it inherit the previous outage's delay.
        if clock() - started >= HEALTHY_RUN_SECONDS:
            backoff = INITIAL_BACKOFF

        print(f"[TRAILING] Reconnecting {symbol} in {backoff:.0f}s")
        sleep(backoff)
        backoff = min(backoff * 2, MAX_BACKOFF)
        restarts += 1
