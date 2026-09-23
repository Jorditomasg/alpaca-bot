"""Unit tests for wheel/feasibility.py — detect a wheel config that can never fire.

2026-08-15 audit. `wheel_state.json` read `cycles: 0, total_premium: 0.0` after
3.5 months live, and the logs were an unbroken wall of:

    [SPREAD] reject 16.5/14.5@2026-09-04 score=0.08 <0.30
    [WHEEL] no decent spread today for SOFI

That is not "a quiet market". `score = credit / max_loss` falls monotonically as
the short strike moves out of the money, so `WHEEL_TARGET_OTM_PCT=0.10` and
`WHEEL_SCORE_THRESHOLD=0.30` are mutually unreachable — measured on the live
SOFI chain, 10% OTM tops out at 0.09 while 0.30 needs a strike ~1.6% OTM.

The bug class is the one CLAUDE.md §7 already names for the kill switch: a
strategy that retires itself in silence and nobody notices for days. Rejecting
every candidate forever must be loud.
"""
from __future__ import annotations

import pytest

import wheel.feasibility as feas


@pytest.fixture()
def state():
    return {}


def _dry_run(state, cycles, *, best=0.09, threshold=0.30, after=5):
    out = []
    for _ in range(cycles):
        out.append(feas.observe(state, best, threshold, infeasible_after=after))
    return out


class TestObserve:
    def test_a_feasible_cycle_is_silent_and_resets_the_streak(self, state):
        _dry_run(state, 4, after=5)
        assert feas.observe(state, 0.42, 0.30, infeasible_after=5) is None
        assert state["dry_cycles"] == 0

    def test_stays_quiet_below_the_threshold_of_cycles(self, state):
        warnings = _dry_run(state, 4, after=5)
        assert warnings == [None, None, None, None]

    def test_warns_once_the_streak_is_long_enough(self, state):
        warnings = _dry_run(state, 5, after=5)
        assert warnings[:4] == [None] * 4
        assert warnings[4] is not None

    def test_the_warning_reports_the_observed_ceiling_and_the_target(self, state):
        msg = _dry_run(state, 5, best=0.09, threshold=0.30, after=5)[-1]
        assert "0.09" in msg and "0.30" in msg

    def test_the_ceiling_is_the_best_score_seen_not_the_last(self, state):
        feas.observe(state, 0.04, 0.30, infeasible_after=3)
        feas.observe(state, 0.17, 0.30, infeasible_after=3)
        msg = feas.observe(state, 0.02, 0.30, infeasible_after=3)
        assert "0.17" in msg

    def test_it_does_not_repeat_the_warning_every_cycle(self, state):
        """A halted strategy shouts once, then shuts up — a warning per 15-min
        cycle is how a real alert gets muted."""
        warnings = _dry_run(state, 12, after=5)
        assert sum(w is not None for w in warnings) == 1

    def test_it_warns_again_after_the_config_recovers_and_dies_again(self, state):
        _dry_run(state, 5, after=5)
        feas.observe(state, 0.42, 0.30, infeasible_after=5)  # a trade became possible
        warnings = _dry_run(state, 5, after=5)
        assert warnings[-1] is not None

    def test_an_unquotable_chain_counts_as_dry_but_never_sets_a_ceiling(self, state):
        """best_score=None means no two-sided quotes at all — a data problem,
        not a calibration one, so it must not masquerade as a measured ceiling."""
        for _ in range(4):
            feas.observe(state, None, 0.30, infeasible_after=5)
        msg = feas.observe(state, None, 0.30, infeasible_after=5)
        assert msg is not None
        assert "no quotable" in msg.lower()
        assert state["best_score_seen"] is None

    def test_state_round_trips_through_json(self, state):
        import json
        _dry_run(state, 3, after=5)
        assert json.loads(json.dumps(state)) == state
