"""Integration smoke test: submit a real multi-leg SOFI put spread to Alpaca paper.

SKIPPED BY DEFAULT — requires ALPACA_API_KEY and ALPACA_SECRET_KEY env vars set
to a paper trading account.

Run manually:
    pytest -m integration

This test:
1. Constructs a far-OTM SOFI bull put spread with minimal notional
2. Submits the mleg order to Alpaca paper
3. Asserts the order was accepted (not rejected)
4. Immediately cancels the order
5. Asserts the cancel was acknowledged

NOTE: Task 8.x — do NOT run this test in CI without paper credentials wired.
"""
import os
import pytest


@pytest.mark.integration
def test_paper_mleg_order_accepted_and_cancelled():
    """Submit a real mleg SOFI bull put spread to paper, verify acceptance, then cancel."""
    from datetime import date, timedelta
    from shared import alpaca_client
    from alpaca.trading.requests import GetOptionContractsRequest
    from alpaca.trading.enums import ContractType
    from wheel.spreads import build_open_order
    from wheel.config import get_config

    # Verify credentials are set — skip gracefully if not
    if not os.getenv("ALPACA_API_KEY") or not os.getenv("ALPACA_SECRET_KEY"):
        pytest.skip("ALPACA_API_KEY or ALPACA_SECRET_KEY not set — skipping integration test")

    cfg = get_config()
    trading = alpaca_client.trading()
    today = date.today()

    # Find two SOFI put contracts at least 14 DTE apart
    min_exp = today + timedelta(days=14)
    max_exp = today + timedelta(days=28)

    contracts_resp = trading.get_option_contracts(GetOptionContractsRequest(
        underlying_symbols=["SOFI"],
        status="active",
        type=ContractType.PUT,
        expiration_date_gte=min_exp,
        expiration_date_lte=max_exp,
        strike_price_gte="5",
        strike_price_lte="12",
    ))

    contracts = contracts_resp.option_contracts
    assert len(contracts) >= 2, (
        f"Expected at least 2 SOFI put contracts in 14-28 DTE range, got {len(contracts)}"
    )

    # Pick the two closest to our target: short ~9.0, long ~7.0
    by_strike = sorted(contracts, key=lambda c: abs(float(c.strike_price) - 9.0))
    short_c = by_strike[0]
    long_c = next(
        (c for c in sorted(contracts, key=lambda c: float(c.strike_price))
         if float(c.strike_price) < float(short_c.strike_price)),
        None
    )

    if long_c is None:
        pytest.skip("Could not find a long leg below the short strike — SOFI chain too narrow today")

    # Submit far-OTM spread with a very low limit credit (unlikely to fill, safe to cancel)
    order = build_open_order(short_c.symbol, long_c.symbol, limit_credit=0.01)
    submitted = trading.submit_order(order)

    assert submitted is not None
    assert submitted.status.value not in ("rejected", "expired"), (
        f"Order was rejected or expired: status={submitted.status}, "
        f"reason={getattr(submitted, 'failed_at', 'n/a')}"
    )

    # Immediately cancel
    trading.cancel_order_by_id(submitted.id)

    # Verify cancel
    order_status = trading.get_order_by_id(submitted.id)
    assert order_status.status.value in (
        "canceled", "pending_cancel", "cancelled"
    ), f"Expected canceled status, got: {order_status.status}"
