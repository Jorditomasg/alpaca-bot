"""Bull put spread selection and multi-leg order construction.

Public API:
  best_bull_put_spread(symbol, current_price, chain, cfg) -> dict | None
  build_open_order(short_symbol, long_symbol, limit_credit) -> LimitOrderRequest
  build_close_order(short_symbol, long_symbol, limit_debit) -> LimitOrderRequest
  spread_mid_price(short_bid, long_ask) -> float

Chain format expected by best_bull_put_spread:
  {
    "spot_price": 9.42,
    "contracts": [
      {"symbol": "...", "type": "put", "strike": 9.0,
       "expiration_date": "2026-01-17", "bid": 0.32, "ask": 0.36},
      ...
    ]
  }
"""
from __future__ import annotations
from typing import TypedDict

from alpaca.trading.requests import LimitOrderRequest, OptionLegRequest
from alpaca.trading.enums import OrderSide, OrderClass, TimeInForce, PositionIntent

from wheel.config import WheelConfig


class SpreadCandidate(TypedDict):
    short_symbol: str
    short_strike: float
    long_symbol: str
    long_strike: float
    expiry: str
    net_credit: float    # dollars per spread (credit * 100)
    max_loss: float      # dollars per spread
    width: float         # actual spread width in dollars
    score: float         # net_credit_per_spread / max_loss


def best_bull_put_spread(
    symbol: str,
    current_price: float,
    chain: dict,
    cfg: WheelConfig,
) -> SpreadCandidate | None:
    """Select the best-scoring bull put spread from a pre-fetched option chain.

    Args:
        symbol:        Underlying ticker (informational, used in log messages).
        current_price: Current spot price of the underlying.
        chain:         Option chain dict with 'contracts' list (see module docstring).
        cfg:           WheelConfig with spread width, DTE bounds, OTM pct, score threshold.

    Returns:
        SpreadCandidate dict or None if no qualifying spread found.
    """
    from datetime import date, datetime

    target_short_strike = current_price * (1.0 - cfg.target_otm_pct)
    today = date.today()

    # Filter to puts within configured DTE range
    filtered: list[dict] = []
    for c in chain.get("contracts", []):
        if c.get("type", "").lower() != "put":
            continue
        try:
            exp = datetime.fromisoformat(str(c["expiration_date"])).date()
        except (ValueError, KeyError):
            continue
        dte = (exp - today).days
        if cfg.target_dte_min <= dte <= cfg.target_dte_max:
            filtered.append({**c, "_expiry": exp})

    if not filtered:
        print(f"[SPREAD] No puts within {cfg.target_dte_min}-{cfg.target_dte_max} DTE for {symbol}")
        return None

    # Group by expiration date
    by_expiry: dict[str, list[dict]] = {}
    for c in filtered:
        key = str(c["_expiry"])
        by_expiry.setdefault(key, []).append(c)

    best: SpreadCandidate | None = None

    for expiry_str, contracts in by_expiry.items():
        contracts_sorted = sorted(contracts, key=lambda c: float(c["strike"]))

        # Short leg: highest strike <= target_short_strike
        shorts = [c for c in contracts_sorted if float(c["strike"]) <= target_short_strike]
        if not shorts:
            continue
        short_c = shorts[-1]
        short_strike = float(short_c["strike"])

        # Long leg: exact width first, then fallback to widest pair not exceeding
        # cfg.spread_width (never silently produce a wider spread than configured).
        long_target = short_strike - cfg.spread_width
        exact = [c for c in contracts_sorted if float(c["strike"]) == long_target]
        if exact:
            long_c = exact[0]
            actual_width = cfg.spread_width
        else:
            # Candidates: strikes below short_strike whose width <= cfg.spread_width
            in_bound = [
                c for c in contracts_sorted
                if float(c["strike"]) < short_strike
                and (short_strike - float(c["strike"])) <= cfg.spread_width
            ]
            if not in_bound:
                continue
            # Pick the widest qualifying long leg (lowest strike = largest width within
            # the configured cap → best risk/reward while respecting the width limit).
            long_c = min(in_bound, key=lambda c: float(c["strike"]))
            actual_width = short_strike - float(long_c["strike"])

        long_strike = float(long_c["strike"])

        # Compute net credit using mid-prices
        short_mid = _mid(short_c)
        long_mid = _mid(long_c)
        if short_mid is None or long_mid is None:
            continue

        credit_per_share = short_mid - long_mid
        if credit_per_share <= 0:
            # Never pay to open a credit spread
            continue

        net_credit_dollars = credit_per_share * 100
        max_loss_dollars = (actual_width * 100) - net_credit_dollars
        if max_loss_dollars <= 0:
            continue

        score = net_credit_dollars / max_loss_dollars

        if score < cfg.score_threshold:
            print(
                f"[SPREAD] reject {short_strike}/{long_strike}@{expiry_str} "
                f"score={score:.2f} <{cfg.score_threshold:.2f}"
            )
            continue

        candidate: SpreadCandidate = {
            "short_symbol": str(short_c["symbol"]),
            "short_strike": short_strike,
            "long_symbol": str(long_c["symbol"]),
            "long_strike": long_strike,
            "expiry": expiry_str,
            "net_credit": round(net_credit_dollars, 2),
            "max_loss": round(max_loss_dollars, 2),
            "width": actual_width,
            "score": round(score, 4),
        }

        if best is None or candidate["score"] > best["score"]:
            best = candidate

    if best is None:
        print(f"[WHEEL] no decent spread today for {symbol} (all candidates scored below {cfg.score_threshold:.2f})")

    return best


def build_open_order(
    short_symbol: str,
    long_symbol: str,
    limit_credit: float,
) -> LimitOrderRequest:
    """Build a bull put spread opening order (sell-to-open short, buy-to-open long).

    The limit_price is the net credit received, expressed positive on a SELL mleg.
    """
    return LimitOrderRequest(
        qty=1,
        order_class=OrderClass.MLEG,
        time_in_force=TimeInForce.DAY,
        limit_price=round(limit_credit, 2),
        legs=[
            OptionLegRequest(
                symbol=short_symbol,
                ratio_qty=1,
                side=OrderSide.SELL,
                position_intent=PositionIntent.SELL_TO_OPEN,
            ),
            OptionLegRequest(
                symbol=long_symbol,
                ratio_qty=1,
                side=OrderSide.BUY,
                position_intent=PositionIntent.BUY_TO_OPEN,
            ),
        ],
    )


def build_close_order(
    short_symbol: str,
    long_symbol: str,
    limit_debit: float,
) -> LimitOrderRequest:
    """Build a bull put spread closing order (buy-to-close short, sell-to-close long).

    The limit_price is the net debit paid to close, expressed positive on a BUY mleg.
    """
    return LimitOrderRequest(
        qty=1,
        order_class=OrderClass.MLEG,
        time_in_force=TimeInForce.DAY,
        limit_price=round(limit_debit, 2),
        legs=[
            OptionLegRequest(
                symbol=short_symbol,
                ratio_qty=1,
                side=OrderSide.BUY,
                position_intent=PositionIntent.BUY_TO_CLOSE,
            ),
            OptionLegRequest(
                symbol=long_symbol,
                ratio_qty=1,
                side=OrderSide.SELL,
                position_intent=PositionIntent.SELL_TO_CLOSE,
            ),
        ],
    )


def spread_mid_price(short_bid: float, long_ask: float) -> float:
    """Compute the conservative current cost-to-close a bull put spread.

    Uses short_bid (what we receive to close the short) minus long_ask
    (what we pay to close the long). This is conservative: it values the
    closing cost, not the opening credit. A lower value means more profit
    for a credit spread we sold to open.
    """
    return short_bid - long_ask


# ── internal helpers ─────────────────────────────────────────────────────────

def _mid(contract: dict) -> float | None:
    """Return the bid-ask midpoint; None if EITHER bid or ask is missing/zero.

    Rejects one-sided quotes (bid=0 with a valid ask, or vice versa) because
    they indicate a stale or unquotable leg that would produce misleading credits.
    """
    try:
        bid = float(contract["bid"])
        ask = float(contract["ask"])
    except (KeyError, TypeError, ValueError):
        return None
    if bid <= 0 or ask <= 0:
        return None
    return (bid + ask) / 2.0
