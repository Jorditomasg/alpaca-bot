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
