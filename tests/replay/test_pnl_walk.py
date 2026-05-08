"""Replay test: walk multiple fixtures and assert P&L calculation consistency.

If only one fixture is available (sofi_synthetic.json), this test is skipped.
Once a second fixture is captured (e.g. sofi_20260515.json), both fixtures are
loaded and the test simulates a SPREAD_OPEN state across the two snapshots,
verifying that the unrealised P&L calculation is consistent with the
spread_mid_price formula.

To generate a second fixture:
    python -m wheel.tools.capture_chain SOFI
"""
import json
import pathlib
import pytest
from wheel.spreads import best_bull_put_spread, spread_mid_price
from wheel.config import get_config

FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "fixtures" / "option_chains"


def _load_all_sofi_fixtures() -> list[dict]:
    """Load all sofi_*.json fixtures in date order, skipping the synthetic file."""
    fixtures = sorted(
        f for f in FIXTURES_DIR.glob("sofi_*.json")
        if "synthetic" not in f.name
    )
    return [json.loads(f.read_text()) for f in fixtures]


@pytest.mark.replay
def test_pnl_walk_across_snapshots():
    """Simulate holding a spread across multiple snapshots and check P&L consistency."""
    real_fixtures = _load_all_sofi_fixtures()
    if len(real_fixtures) < 2:
        pytest.skip(
            "Need at least 2 real sofi_<YYYYMMDD>.json fixtures for P&L walk test. "
            "Run `python -m wheel.tools.capture_chain SOFI` on two different trading days."
        )

    cfg = get_config()

    # Select spread from first snapshot
    first = real_fixtures[0]
    result = best_bull_put_spread("SOFI", first["spot_price"], first, cfg)
    if result is None:
        pytest.skip("No qualifying spread in first fixture — cannot run P&L walk.")

    short_sym   = result["short_symbol"]
    long_sym    = result["long_symbol"]
    net_credit  = result["net_credit"]

    # Walk remaining snapshots
    for fixture in real_fixtures[1:]:
        contracts_by_sym = {c["symbol"]: c for c in fixture["contracts"]}
        sc = contracts_by_sym.get(short_sym)
        lc = contracts_by_sym.get(long_sym)
        if sc is None or lc is None:
            continue  # contract may have expired or rolled off the chain

        short_bid = float(sc["bid"])
        long_ask  = float(lc["ask"])
        current_mid = spread_mid_price(short_bid, long_ask)

        # Unrealised P&L per spread = (net_credit_per_share - current_cost) * 100
        unrealised_pnl = (net_credit / 100.0 - current_mid) * 100.0

        # Sanity: unrealised P&L is bounded by [-max_loss, net_credit]
        assert unrealised_pnl >= -result["max_loss"] - 1.0, (
            f"unrealised_pnl=${unrealised_pnl:.2f} exceeds max_loss=${result['max_loss']:.2f}"
        )
        assert unrealised_pnl <= result["net_credit"] + 1.0, (
            f"unrealised_pnl=${unrealised_pnl:.2f} exceeds net_credit=${result['net_credit']:.2f}"
        )
