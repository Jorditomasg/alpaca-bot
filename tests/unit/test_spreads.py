"""Unit tests for wheel/spreads.py — selection, scoring, and order construction."""
import pytest
from alpaca.trading.enums import OrderClass, PositionIntent, OrderSide
from wheel.spreads import best_bull_put_spread, build_open_order, build_close_order, spread_mid_price
from wheel.config import get_config


# ── helpers ───────────────────────────────────────────────────────────────────

# Good credit levels that pass the 0.30 score threshold:
#   short_mid=0.61, long_mid=0.11 → credit=$0.50/share → net_credit=$50
#   max_loss = (2*100) - 50 = $150 → score=50/150≈0.333 ≥ 0.30 ✓
_GOOD_SHORT_BID  = 0.60
_GOOD_SHORT_ASK  = 0.62
_GOOD_LONG_BID   = 0.10
_GOOD_LONG_ASK   = 0.12
_EXPIRY_WITHIN   = "2026-05-29"  # ~21 DTE from 2026-05-08 (within 14-28 DTE window)


def _make_chain(
    spot: float = 10.0,
    expiry: str = _EXPIRY_WITHIN,
    short_strike: float = 9.0,
    long_strike: float = 7.0,
    short_bid: float = _GOOD_SHORT_BID,
    short_ask: float = _GOOD_SHORT_ASK,
    long_bid: float = _GOOD_LONG_BID,
    long_ask: float = _GOOD_LONG_ASK,
) -> dict:
    return {
        "spot_price": spot,
        "contracts": [
            {
                "symbol": f"SOFI{expiry.replace('-','')}P{int(short_strike*1000):08d}",
                "type": "put",
                "strike": short_strike,
                "expiration_date": expiry,
                "bid": short_bid,
                "ask": short_ask,
            },
            {
                "symbol": f"SOFI{expiry.replace('-','')}P{int(long_strike*1000):08d}",
                "type": "put",
                "strike": long_strike,
                "expiration_date": expiry,
                "bid": long_bid,
                "ask": long_ask,
            },
        ],
    }


@pytest.fixture
def default_cfg():
    return get_config()


# ── happy path strike selection ───────────────────────────────────────────────

def test_happy_path_selects_correct_strikes(default_cfg):
    """With a clean chain, should pick the strike closest-below 10%OTM."""
    # spot=10, OTM=10% → target short strike = 9.0; long = 7.0
    chain = _make_chain(spot=10.0, short_strike=9.0, long_strike=7.0)
    result = best_bull_put_spread("SOFI", 10.0, chain, default_cfg)
    assert result is not None
    assert result["short_strike"] == 9.0
    assert result["long_strike"] == 7.0


def test_net_credit_positive(default_cfg):
    chain = _make_chain()
    result = best_bull_put_spread("SOFI", 10.0, chain, default_cfg)
    assert result is not None
    assert result["net_credit"] > 0


def test_net_credit_calculation(default_cfg):
    """net_credit = (short_mid - long_mid) * 100.

    short_mid=(0.60+0.62)/2=0.61, long_mid=(0.10+0.12)/2=0.11
    credit_per_share = 0.50; net_credit = 50.0
    """
    chain = _make_chain()
    result = best_bull_put_spread("SOFI", 10.0, chain, default_cfg)
    assert result is not None
    assert abs(result["net_credit"] - 50.0) < 0.01


def test_spread_width_in_result(default_cfg):
    chain = _make_chain(short_strike=9.0, long_strike=7.0)
    result = best_bull_put_spread("SOFI", 10.0, chain, default_cfg)
    assert result is not None
    assert result["width"] == 2.0


def test_score_above_threshold(default_cfg):
    """Confirm the score reported is ≥ threshold for our good-credit test chain."""
    chain = _make_chain()
    result = best_bull_put_spread("SOFI", 10.0, chain, default_cfg)
    assert result is not None
    assert result["score"] >= default_cfg.score_threshold


# ── score threshold rejection ─────────────────────────────────────────────────

def test_score_threshold_rejection(default_cfg, capsys):
    """A spread scoring below 0.30 must be rejected and None returned.

    short_mid=0.01, long_mid=0.0005 → credit≈$0.0095/share → score≈0.005 < 0.30
    """
    chain = _make_chain(
        short_bid=0.009,
        short_ask=0.011,
        long_bid=0.0004,
        long_ask=0.0006,
        short_strike=9.0,
        long_strike=7.0,
    )
    result = best_bull_put_spread("SOFI", 10.0, chain, default_cfg)
    assert result is None
    captured = capsys.readouterr()
    assert "reject" in captured.out.lower() or "no decent spread" in captured.out.lower()


# ── missing-exact-width fallback ──────────────────────────────────────────────

def test_fallback_when_exact_long_leg_missing(default_cfg):
    """Fallback picks the widest long leg NOT EXCEEDING cfg.spread_width.

    width=2, short=9.0 → long_target=7.0.
    Available: 7.50 (width=1.5, in-bound) and 6.50 (width=2.5, exceeds cap).
    Expected: 7.50 selected; 6.50 rejected; spread width=1.5.
    """
    expiry = _EXPIRY_WITHIN
    chain = {
        "spot_price": 10.0,
        "contracts": [
            {
                "symbol": "SOFI20260529P00009000",
                "type": "put",
                "strike": 9.0,
                "expiration_date": expiry,
                # short_mid=0.71, long_mid(7.50)=0.11 → credit≈$60
                # width=1.5 → max_loss=(1.5*100)-60=$90 → score=60/90≈0.67 ≥ 0.30 ✓
                "bid": 0.70,
                "ask": 0.72,
            },
            {
                "symbol": "SOFI20260529P00007500",
                "type": "put",
                "strike": 7.5,   # width=1.5 → within cap
                "expiration_date": expiry,
                "bid": _GOOD_LONG_BID,
                "ask": _GOOD_LONG_ASK,
            },
            {
                "symbol": "SOFI20260529P00006500",
                "type": "put",
                "strike": 6.5,   # width=2.5 → exceeds cap → must be rejected
                "expiration_date": expiry,
                "bid": _GOOD_LONG_BID,
                "ask": _GOOD_LONG_ASK,
            },
        ],
    }
    result = best_bull_put_spread("SOFI", 10.0, chain, default_cfg)
    # Should pick 7.50 (widest within cap); 6.50 is rejected
    assert result is not None
    assert result["long_strike"] == 7.5
    assert result["width"] == pytest.approx(1.5, abs=0.001)


def test_fallback_rejects_wider_than_cap(default_cfg):
    """When ALL fallback candidates exceed cfg.spread_width, return None.

    width=2, short=9.0, only 6.5 available (width=2.5 > cap) → None.
    """
    expiry = _EXPIRY_WITHIN
    chain = {
        "spot_price": 10.0,
        "contracts": [
            {
                "symbol": "SOFI20260529P00009000",
                "type": "put",
                "strike": 9.0,
                "expiration_date": expiry,
                "bid": 0.70,
                "ask": 0.72,
            },
            {
                "symbol": "SOFI20260529P00006500",
                "type": "put",
                "strike": 6.5,   # width=2.5 > cfg.spread_width=2.0 → rejected
                "expiration_date": expiry,
                "bid": _GOOD_LONG_BID,
                "ask": _GOOD_LONG_ASK,
            },
        ],
    }
    result = best_bull_put_spread("SOFI", 10.0, chain, default_cfg)
    assert result is None


# ── empty / bad chain ─────────────────────────────────────────────────────────

def test_empty_chain_returns_none(default_cfg):
    chain = {"spot_price": 10.0, "contracts": []}
    assert best_bull_put_spread("SOFI", 10.0, chain, default_cfg) is None


def test_no_contracts_in_dte_range_returns_none(default_cfg):
    # Put expiry 1 day from now → outside 14-28 DTE window
    chain = _make_chain(expiry="2026-05-09")  # 1 day from 2026-05-08
    assert best_bull_put_spread("SOFI", 10.0, chain, default_cfg) is None


def test_negative_credit_skipped(default_cfg):
    """Spread where long_mid > short_mid (upside-down chain) is skipped."""
    chain = _make_chain(
        short_bid=0.05, short_ask=0.07,  # short_mid = 0.06
        long_bid=0.30, long_ask=0.40,    # long_mid  = 0.35 → credit negative
    )
    assert best_bull_put_spread("SOFI", 10.0, chain, default_cfg) is None


# ── One-sided quote rejection (Fix #6) ───────────────────────────────────────

def test_one_sided_quote_bid_zero_rejects_spread(default_cfg):
    """A leg with bid=0 must cause the spread to be rejected (not opened).

    short_bid=0, short_ask=0.50 → _mid returns None → spread candidate rejected.
    """
    expiry = _EXPIRY_WITHIN
    chain = {
        "spot_price": 10.0,
        "contracts": [
            {
                "symbol": "SOFI20260529P00009000",
                "type": "put",
                "strike": 9.0,
                "expiration_date": expiry,
                "bid": 0.0,   # one-sided quote: bid missing
                "ask": 0.50,
            },
            {
                "symbol": "SOFI20260529P00007000",
                "type": "put",
                "strike": 7.0,
                "expiration_date": expiry,
                "bid": _GOOD_LONG_BID,
                "ask": _GOOD_LONG_ASK,
            },
        ],
    }
    result = best_bull_put_spread("SOFI", 10.0, chain, default_cfg)
    assert result is None


def test_valid_both_legs_proceeds(default_cfg):
    """Both legs with valid bid and ask → spread is found (regression)."""
    chain = _make_chain()
    result = best_bull_put_spread("SOFI", 10.0, chain, default_cfg)
    assert result is not None


def test_one_sided_quote_ask_zero_rejects_spread(default_cfg):
    """A leg with ask=0 must also cause rejection (symmetry with bid=0 case)."""
    expiry = _EXPIRY_WITHIN
    chain = {
        "spot_price": 10.0,
        "contracts": [
            {
                "symbol": "SOFI20260529P00009000",
                "type": "put",
                "strike": 9.0,
                "expiration_date": expiry,
                "bid": 0.60,
                "ask": 0.0,  # one-sided: ask missing
            },
            {
                "symbol": "SOFI20260529P00007000",
                "type": "put",
                "strike": 7.0,
                "expiration_date": expiry,
                "bid": _GOOD_LONG_BID,
                "ask": _GOOD_LONG_ASK,
            },
        ],
    }
    result = best_bull_put_spread("SOFI", 10.0, chain, default_cfg)
    assert result is None


# ── order shape validation ────────────────────────────────────────────────────

def test_build_open_order_shape():
    order = build_open_order("SOFI260117P00009000", "SOFI260117P00007000", 0.30)
    assert order.order_class == OrderClass.MLEG
    assert order.limit_price == 0.30
    assert len(order.legs) == 2

    short_leg = order.legs[0]
    long_leg = order.legs[1]

    assert short_leg.symbol == "SOFI260117P00009000"
    assert short_leg.side == OrderSide.SELL
    assert short_leg.position_intent == PositionIntent.SELL_TO_OPEN

    assert long_leg.symbol == "SOFI260117P00007000"
    assert long_leg.side == OrderSide.BUY
    assert long_leg.position_intent == PositionIntent.BUY_TO_OPEN


def test_build_close_order_shape():
    order = build_close_order("SOFI260117P00009000", "SOFI260117P00007000", 0.15)
    assert order.order_class == OrderClass.MLEG
    assert order.limit_price == 0.15
    assert len(order.legs) == 2

    short_leg = order.legs[0]
    long_leg = order.legs[1]

    assert short_leg.symbol == "SOFI260117P00009000"
    assert short_leg.side == OrderSide.BUY
    assert short_leg.position_intent == PositionIntent.BUY_TO_CLOSE

    assert long_leg.symbol == "SOFI260117P00007000"
    assert long_leg.side == OrderSide.SELL
    assert long_leg.position_intent == PositionIntent.SELL_TO_CLOSE


def test_build_open_order_limit_price_rounded():
    order = build_open_order("X", "Y", 0.3456789)
    assert order.limit_price == 0.35


def test_spread_mid_price():
    """spread_mid_price = short_bid - long_ask (conservative close cost)."""
    # short bid=0.20, long ask=0.08 → mid = 0.12
    assert spread_mid_price(0.20, 0.08) == pytest.approx(0.12, abs=0.001)
