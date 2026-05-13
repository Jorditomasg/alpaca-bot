"""Unit tests for copy_trader/scraper.py — HTML parsing edge cases."""
import copy_trader.scraper as scraper


# ── Bug 1 regression: tag-stripping must not glue brand suffix to ticker ────


def _row_html(asset_inner_html: str) -> str:
    """Wrap an asset cell in a minimal row with the 10 cells _parse_row expects.

    Politician / date / type / amount cells are filled with stubs.
    """
    cells = [
        '<span>John Boozman</span><span>Republican</span>',  # politician
        asset_inner_html,                                     # asset (under test)
        '<span>10 Mar2026</span>',                            # pub_date
        '<span>05 Mar2026</span>',                            # tx_date
        '<span></span>',                                      # 4 (unused)
        '<span></span>',                                      # 5 (unused)
        '<span>buy</span>',                                   # tx_type
        '<span>1K-15K</span>',                                # amount
        '<span></span>',                                      # 8 (unused)
        '<span></span>',                                      # 9 (unused)
    ]
    tds = "".join(f"<td>{c}</td>" for c in cells)
    return f'<a href="/trades/12345"></a><table>{tds}</table>'


def test_ticker_extracted_when_brand_suffix_is_in_separate_span():
    """Real bug: <span>...ETF</span><span>IWD:US</span> → ticker must be IWD,
    not ETFIWD (tag-stripping was gluing the spans together)."""
    html = _row_html('<span>iShares Russell 1000 Value ETF</span><span>IWD:US</span>')

    cells = scraper._extract_cells(html)
    # Skip the wrapper <table> td — the relevant cells are inside
    row = cells[:10]
    trade = scraper._parse_row(row, "12345")

    assert trade is not None
    assert trade["ticker"] == "IWD", (
        f"Expected IWD, got {trade['ticker']!r} — tag stripping glued ETF to IWD"
    )


def test_ticker_extracted_when_etn_suffix_is_in_separate_span():
    """ETN variant: <span>...ETN</span><span>XYZ:US</span> → ticker = XYZ."""
    html = _row_html('<span>iPath Series B Bloomberg ETN</span><span>SCHP:US</span>')

    cells = scraper._extract_cells(html)
    row = cells[:10]
    trade = scraper._parse_row(row, "12345")

    assert trade is not None
    assert trade["ticker"] == "SCHP"


def test_ticker_extracted_when_plc_suffix_is_in_separate_span():
    """PLC company suffix variant — same glueing bug."""
    html = _row_html('<span>Janus Henderson Group PLC</span><span>JHG:US</span>')

    cells = scraper._extract_cells(html)
    row = cells[:10]
    trade = scraper._parse_row(row, "12345")

    assert trade is not None
    assert trade["ticker"] == "JHG"


# ── Amount range parsing — needed by copier's min_amount filter ─────────────


def test_parse_amount_range_K_suffix():
    assert scraper._parse_amount_range("1K-15K") == (1_000, 15_000)
    assert scraper._parse_amount_range("15K-50K") == (15_000, 50_000)


def test_parse_amount_range_M_suffix():
    assert scraper._parse_amount_range("500K-1M") == (500_000, 1_000_000)
    assert scraper._parse_amount_range("1M-5M") == (1_000_000, 5_000_000)


def test_parse_amount_range_with_dollar_signs_and_spaces():
    assert scraper._parse_amount_range("$1K - $15K") == (1_000, 15_000)


def test_parse_amount_range_unparseable_returns_zero_zero():
    assert scraper._parse_amount_range("N/A") == (0, 0)
    assert scraper._parse_amount_range("") == (0, 0)


def test_parsed_trade_includes_numeric_amount_mid():
    """The trade dict must surface numeric low/high/mid so the copier filter works."""
    cells = [
        '<span>John Boozman</span><span>Republican</span>',
        '<span>Apple Inc</span><span>AAPL:US</span>',
        '<span>10 Mar2026</span>',
        '<span>05 Mar2026</span>',
        '<span></span>',
        '<span></span>',
        '<span>buy</span>',
        '<span>15K-50K</span>',
        '<span></span>',
        '<span></span>',
    ]
    html = "<a href=\"/trades/12345\"></a><table>" + "".join(f"<td>{c}</td>" for c in cells) + "</table>"
    parsed = scraper._extract_cells(html)
    trade = scraper._parse_row(parsed[:10], "12345")

    assert trade is not None
    assert trade["amount_low"] == 15_000
    assert trade["amount_high"] == 50_000
    assert trade["amount_mid"] == 32_500
