"""Live rotation shell — driven by a fake broker (no network)."""
from datetime import date

import pytest

from rotation.config import RotationConfig
from rotation.engine import Broker, due, iso_week, run_rebalance

CFG = RotationConfig(universe=("AAA", "BBB", "CCC"), top_n=2, cash_symbol="CASHX")


def _rising(step):
    return [100.0 + step * i for i in range(300)]


class Fake:
    def __init__(self, positions=None, equity=1000.0, cash=900.0):
        self.calls = []
        self._pos = positions or {}
        self._acct = {"equity": equity, "cash": cash}

    def broker(self):
        return Broker(
            account=lambda: self._acct,
            positions=lambda: self._pos,
            closes=lambda syms, today: {"AAA": _rising(0.5), "BBB": _rising(0.3), "CCC": _rising(0.1), "CASHX": _rising(0.0)},
            buy=lambda sym, notional=None, qty=None: self.calls.append(("BUY", sym, notional)),
            sell=lambda sym, notional=None, qty=None: self.calls.append(("SELL", sym, notional)),
            close_position=lambda sym: self.calls.append(("CLOSE", sym, None)),
            sleep=lambda s: self.calls.append(("SLEEP", s, None)),
        )


def test_buys_top_names_with_half_of_equity():
    f = Fake()
    res = run_rebalance(CFG, f.broker(), date(2026, 10, 13), exclude=set(), halted=False, log=lambda m: None)
    assert res["budget"] == 500.0
    assert ("BUY", "AAA", 250.0) in f.calls and ("BUY", "BBB", 250.0) in f.calls


def test_never_selects_or_sells_a_symbol_another_strategy_holds():
    f = Fake(positions={"AAA": (1.0, 120.0)})
    run_rebalance(CFG, f.broker(), date(2026, 10, 13), exclude={"AAA"}, halted=False, log=lambda m: None)
    assert all(c[1] != "AAA" for c in f.calls)


def test_kill_switch_blocks_buys_but_not_sells():
    f = Fake(positions={"CCC": (2.0, 200.0)})
    run_rebalance(CFG, f.broker(), date(2026, 10, 13), exclude=set(), halted=True, log=lambda m: None)
    assert ("CLOSE", "CCC", None) in f.calls
    assert not any(c[0] == "BUY" for c in f.calls)


def test_sells_execute_before_buys():
    f = Fake(positions={"CCC": (2.0, 200.0)})
    run_rebalance(CFG, f.broker(), date(2026, 10, 13), exclude=set(), halted=False, log=lambda m: None)
    kinds = [c[0] for c in f.calls]
    assert kinds.index("CLOSE") < kinds.index("SLEEP") < kinds.index("BUY")


def test_failed_order_does_not_abort_the_rest():
    f = Fake()
    b = f.broker()
    def flaky(sym, notional=None, qty=None):
        if sym == "AAA":
            raise RuntimeError("insufficient buying power")
        f.calls.append(("BUY", sym, notional))
    b.buy = flaky
    res = run_rebalance(CFG, b, date(2026, 10, 13), exclude=set(), halted=False, log=lambda m: None)
    assert ("BUY", "BBB", 250.0) in f.calls
    assert [o[1] for o in res["orders"]] == ["BBB"]


def test_rebalance_due_once_per_iso_week():
    st = {"last_rebalance_week": iso_week(date(2026, 10, 13))}
    assert not due(st, date(2026, 10, 16))
    assert due(st, date(2026, 10, 19))
    assert due({}, date(2026, 10, 13))
