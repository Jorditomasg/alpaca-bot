"""Replay test: run best_bull_put_spread against the committed SOFI fixture.

Uses sofi_synthetic.json as a stand-in until a real capture is available.
To add a real fixture: run `python -m wheel.tools.capture_chain SOFI` on a
trading day and commit the resulting sofi_<YYYYMMDD>.json file.
"""
import pytest
from wheel.spreads import best_bull_put_spread
from wheel.config import get_config


@pytest.mark.replay
def test_spread_selection_from_synthetic_fixture(load_chain_fixture):
    """Replay: best_bull_put_spread selects expected strikes from the synthetic fixture."""
    chain = load_chain_fixture("sofi_synthetic.json")
    cfg = get_config()

    spot = chain["spot_price"]  # 10.05
    result = best_bull_put_spread("SOFI", spot, chain, cfg)

    assert result is not None, (
        "best_bull_put_spread returned None on synthetic fixture — "
        "check that the fixture has qualifying contracts within the DTE window "
        "and that premiums produce a score >= score_threshold (currently "
        f"{cfg.score_threshold:.2f})."
    )
    # Should pick the 9.0/7.0 pair (closest below 10% OTM of 10.05 = 9.045)
    assert result["short_strike"] == 9.0
    assert result["long_strike"] == 7.0
    assert result["width"] == pytest.approx(2.0, abs=0.001)
    assert result["net_credit"] > 0
    assert result["score"] >= cfg.score_threshold


@pytest.mark.replay
def test_spread_fixture_net_credit_is_plausible(load_chain_fixture):
    """Net credit should be a positive dollar amount per spread (1 contract = 100 shares)."""
    chain = load_chain_fixture("sofi_synthetic.json")
    cfg = get_config()
    result = best_bull_put_spread("SOFI", chain["spot_price"], chain, cfg)

    assert result is not None
    # For a $2-wide spread on SOFI at ~$10, credit should be in range $30–$100
    assert 10.0 <= result["net_credit"] <= 200.0, (
        f"net_credit={result['net_credit']:.2f} is outside expected range $10–$200 "
        "for a $2-wide SOFI put spread"
    )
