"""Unit tests for trailing/stream.py — supervised price stream.

2026-07-30 incident: alpaca-bot logs held ~7,900 websocket tracebacks, almost
all `socket.gaierror: Temporary failure in name resolution`, plus 829
`ValueError: connection limit exceeded`. The SDK reconnects internally with no
backoff, so a local DNS blip turned into a hot reconnect loop that burned
through Alpaca's one-connection-per-account limit — leaving the trailing stop
with no price feed, which is the one thing keeping that position bounded.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import trailing.stream as stream


class FakeStream:
    """StockDataStream double whose run() outcome is scripted per instance."""

    def __init__(self, outcomes: list, durations: list | None = None):
        self._outcomes = outcomes
        self.subscribed: list = []
        self.stopped = False
        self.closed = False
        self.stop_ws_awaited = False

    def subscribe_trades(self, handler, symbol):
        self.subscribed.append(symbol)

    def run(self):
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome

    def stop(self):
        self.stopped = True

    async def stop_ws(self):
        self.stop_ws_awaited = True

    def close(self):
        self.closed = True


@pytest.fixture()
def harness():
    """Returns (make_factory, sleeps) — sleeps records the backoff schedule."""
    sleeps: list[float] = []
    created: list[FakeStream] = []

    def make_factory(outcomes):
        def factory():
            s = FakeStream(outcomes)
            created.append(s)
            return s
        return factory

    return make_factory, sleeps, created


async def _noop(price: float) -> None:  # pragma: no cover - never awaited
    pass


def test_reconnects_after_the_stream_drops(harness):
    make_factory, sleeps, created = harness
    factory = make_factory([ConnectionError("dns"), ConnectionError("dns"), None])

    stream.start(
        "AMZN", _noop,
        stream_factory=factory, sleep=sleeps.append, max_restarts=2,
    )

    assert len(created) == 3
    assert all(s.subscribed == ["AMZN"] for s in created)


def test_old_connection_is_released_before_reconnecting(harness):
    """Alpaca counts the stale session; not closing it is what exhausted the
    one-connection limit."""
    make_factory, sleeps, created = harness
    factory = make_factory([ConnectionError("dns"), None])

    stream.start(
        "AMZN", _noop,
        stream_factory=factory, sleep=sleeps.append, max_restarts=1,
    )

    assert created[0].stopped is True


def test_backoff_grows_exponentially_instead_of_hot_looping(harness):
    make_factory, sleeps, created = harness
    factory = make_factory([ConnectionError("dns")] * 5)

    stream.start(
        "AMZN", _noop,
        stream_factory=factory, sleep=sleeps.append, max_restarts=4,
    )

    assert sleeps == sorted(sleeps)
    assert sleeps[0] == stream.INITIAL_BACKOFF
    assert sleeps[1] > sleeps[0]
    assert len(set(sleeps)) > 1


def test_backoff_is_capped(harness):
    make_factory, sleeps, created = harness
    factory = make_factory([ConnectionError("dns")] * 40)

    stream.start(
        "AMZN", _noop,
        stream_factory=factory, sleep=sleeps.append, max_restarts=39,
    )

    assert max(sleeps) == stream.MAX_BACKOFF


def test_backoff_resets_after_a_healthy_run(harness):
    """A stream that held for hours then dropped should retry immediately-ish,
    not inherit the previous outage's 5-minute delay."""
    make_factory, sleeps, created = harness
    factory = make_factory([ConnectionError("a"), ConnectionError("b"), ConnectionError("c")])

    ticks = iter([0.0, 1.0, 1.0, 1.0 + stream.HEALTHY_RUN_SECONDS + 1, 0.0, 5.0])
    stream.start(
        "AMZN", _noop,
        stream_factory=factory, sleep=sleeps.append,
        clock=lambda: next(ticks), max_restarts=2,
    )

    # 1st drop was instant → backoff grows; 2nd ran healthy → backoff resets.
    assert sleeps[-1] == stream.INITIAL_BACKOFF


def test_clean_return_from_run_also_reconnects(harness):
    """run() returning (rather than raising) still means no price feed."""
    make_factory, sleeps, created = harness
    factory = make_factory([None, None])

    stream.start(
        "AMZN", _noop,
        stream_factory=factory, sleep=sleeps.append, max_restarts=1,
    )

    assert len(created) == 2


def test_a_failing_stop_does_not_abort_the_supervisor(harness):
    make_factory, sleeps, created = harness

    def factory():
        s = FakeStream([ConnectionError("dns")])
        s.stop = MagicMock(side_effect=RuntimeError("already closed"))
        created.append(s)
        return s

    stream.start(
        "AMZN", _noop,
        stream_factory=factory, sleep=sleeps.append, max_restarts=1,
    )

    assert len(created) == 2


class TestStreamHandle:
    """A closed trailing position must be able to end its own stream.

    2026-08-15: the AMZN trailing position stopped out ("Floor breached —
    price=$265.03 floor=$265.04") and the strategy never traded again. The
    supervisor kept streaming AMZN forever while `on_price` returned early on
    every tick because the state file was gone — burning Alpaca's single data
    connection to feed a strategy that had nothing left to manage. Only a
    container restart revived it. The supervisor needs an off switch.
    """

    def test_stop_ends_the_supervisor_instead_of_reconnecting(self, harness):
        make_factory, sleeps, created = harness
        handle = stream.StreamHandle()

        def factory():
            s = FakeStream([None])
            created.append(s)
            handle.stop()  # position closed while the stream was live
            return s

        stream.start(
            "AMZN", _noop,
            stream_factory=factory, sleep=sleeps.append, handle=handle,
        )

        assert len(created) == 1, "stopped supervisor must not reconnect"
        assert sleeps == [], "stopped supervisor must not sleep on a backoff"

    def test_stop_releases_the_live_stream_so_run_unblocks(self, harness):
        """run() blocks in a worker thread; stop() has to reach into it."""
        make_factory, sleeps, created = harness
        handle = stream.StreamHandle()
        live = FakeStream([None])

        handle._bind(live)
        handle.stop()

        assert live.stopped is True

    def test_stop_before_start_never_opens_a_connection(self, harness):
        make_factory, sleeps, created = harness
        handle = stream.StreamHandle()
        handle.stop()

        stream.start(
            "AMZN", _noop,
            stream_factory=make_factory([None]), sleep=sleeps.append,
            handle=handle,
        )

        assert created == []

    def test_stop_is_idempotent_and_survives_a_failing_release(self, harness):
        handle = stream.StreamHandle()
        live = FakeStream([None])
        live.stop = MagicMock(side_effect=RuntimeError("already closed"))
        handle._bind(live)

        handle.stop()
        handle.stop()

        assert handle.stopped is True

    def test_astop_signals_the_socket_without_the_cross_thread_hop(self):
        """`on_price` runs *inside* the stream's own event loop.

        The SDK's `stop()` does `run_coroutine_threadsafe(...).result(timeout=5)`,
        so calling it from that loop blocks the very loop that must service the
        coroutine — a guaranteed 5s stall on every exit. `stop_ws()` only pushes
        to the stop queue, so it is the safe signal from inside.
        """
        import asyncio

        handle = stream.StreamHandle()
        live = FakeStream([None])
        live.stop = MagicMock(side_effect=AssertionError("must not cross threads"))
        handle._bind(live)

        asyncio.run(handle.astop())

        assert handle.stopped is True
        assert live.stop_ws_awaited is True

    def test_astop_falls_back_to_release_when_stop_ws_is_absent(self):
        import asyncio

        class NoStopWs(FakeStream):
            stop_ws = None

        handle = stream.StreamHandle()
        live = NoStopWs([None])
        handle._bind(live)

        asyncio.run(handle.astop())

        assert live.stopped is True

    def test_without_a_handle_the_supervisor_behaves_exactly_as_before(self, harness):
        make_factory, sleeps, created = harness

        stream.start(
            "AMZN", _noop,
            stream_factory=make_factory([ConnectionError("dns"), None]),
            sleep=sleeps.append, max_restarts=1,
        )

        assert len(created) == 2


def test_handler_forwards_the_trade_price(harness):
    make_factory, sleeps, created = harness
    seen: list[float] = []

    async def record(price: float) -> None:
        seen.append(price)

    captured = {}

    class CapturingStream(FakeStream):
        def subscribe_trades(self, handler, symbol):
            captured["handler"] = handler
            super().subscribe_trades(handler, symbol)

    def factory():
        s = CapturingStream([None])
        created.append(s)
        return s

    stream.start(
        "AMZN", record,
        stream_factory=factory, sleep=sleeps.append, max_restarts=0,
    )

    import asyncio
    asyncio.run(captured["handler"](MagicMock(price="238.19")))
    assert seen == [238.19]
