"""In-memory pause/resume flags for each strategy.

Restart resets all flags to active. Persistence is deliberately omitted:
a bot stuck paused after a crash is worse than re-pausing manually.
"""
import asyncio

_STRATEGIES = ("trailing", "copy", "wheel")


class ControlFlags:
    def __init__(self):
        self._events: dict[str, asyncio.Event] = {
            name: asyncio.Event() for name in _STRATEGIES
        }
        for ev in self._events.values():
            ev.set()

    def _targets(self, strategy: str) -> list[str]:
        if strategy == "all":
            return list(_STRATEGIES)
        return [strategy] if strategy in self._events else []

    def pause(self, strategy: str) -> None:
        for name in self._targets(strategy):
            self._events[name].clear()

    def resume(self, strategy: str) -> None:
        for name in self._targets(strategy):
            self._events[name].set()

    def is_paused(self, strategy: str) -> bool:
        ev = self._events.get(strategy)
        return ev is not None and not ev.is_set()

    async def wait_if_paused(self, strategy: str) -> None:
        ev = self._events.get(strategy)
        if ev is None:
            return
        await ev.wait()


flags = ControlFlags()
