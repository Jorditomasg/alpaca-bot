"""Unit tests for copy_trader/scraper.py — HTML parsing edge cases + pagination."""
import copy_trader.scraper as scraper


# ── Pagination ───────────────────────────────────────────────────────────────


def _page_html(trade_ids: list[str]) -> str:
    """Minimal page: one anchor + one 10-cell row per trade id."""
    rows = []
    anchors = []
    for tid in trade_ids:
        anchors.append(f'<a href="/trades/{tid}"></a>')
        cells = [
            '<span>John Boozman</span><span>Republican</span>',
            '<span>Apple Inc</span><span>AAPL:US</span>',
            '<span>10 Mar2026</span>',
            '<span>05 Mar2026</span>',
            '<span></span>', '<span></span>',
            '<span>buy</span>',
            '<span>15K-50K</span>',
            '<span></span>', '<span></span>',
        ]
        rows.append("".join(f"<td>{c}</td>" for c in cells))
    return "".join(anchors) + "<table>" + "".join(rows) + "</table>"


def test_fetch_trades_walks_multiple_pages_and_dedupes(monkeypatch):
    """fetch_trades(pages=2) must merge both pages, deduping overlapping ids."""
    pages = {1: _page_html(["111", "222"]), 2: _page_html(["222", "333"])}
    monkeypatch.setattr(
        scraper, "_get_html",
        lambda client, page=1, retries=3: pages.get(page),
    )
    monkeypatch.setattr(scraper.time, "sleep", lambda *_: None)

    trades = scraper.fetch_trades(pages=2)

    assert [t["id"] for t in trades] == ["111", "222", "333"]


def test_fetch_trades_returns_collected_when_a_page_fails(monkeypatch):
    """A failed page must not discard what earlier pages already produced."""
    pages = {1: _page_html(["111", "222"]), 2: None}
    monkeypatch.setattr(
        scraper, "_get_html",
        lambda client, page=1, retries=3: pages.get(page),
    )
    monkeypatch.setattr(scraper.time, "sleep", lambda *_: None)

    trades = scraper.fetch_trades(pages=3)

    assert [t["id"] for t in trades] == ["111", "222"]


def test_fetch_trades_default_fetches_single_page(monkeypatch):
    requested: list[int] = []

    def fake_get_html(client, page=1, retries=3):
        requested.append(page)
        return _page_html(["111"])

    monkeypatch.setattr(scraper, "_get_html", fake_get_html)

    scraper.fetch_trades()

    assert requested == [1]


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


# ── Live formats (regression: 2026-10-02) ───────────────────────────────────
# capitoltrades.com renders traded dates as "22 Sept 2026" (space before the
# year, 4-letter "Sept"), recent publication dates as "13:02 Today" /
# "20:15 Yesterday", and amount ranges with an EN DASH ("1K–15K"). The old
# regexes matched none of these, so every trade parsed with empty dates and
# amount 0: the copier dropped every buy and every politician scored 0.450.

from datetime import datetime as _dt
from pathlib import Path as _Path

_NOW = _dt(2026, 10, 2, 21, 18)


def test_parse_date_live_format_with_space_and_four_letter_month():
    assert scraper._parse_date("22 Sept 2026") == "2026-09-22"
    assert scraper._parse_date("4 Sept 2026") == "2026-09-04"
    assert scraper._parse_date("1 June 2026") == "2026-06-01"
    assert scraper._parse_date("15 Oct 2026") == "2026-10-15"


def test_parse_date_legacy_glued_format_still_works():
    assert scraper._parse_date("10 Mar2026") == "2026-03-10"


def test_parse_date_relative_today_and_yesterday():
    assert scraper._parse_date("13:02 Today", now=_NOW) == "2026-10-02"
    assert scraper._parse_date("20:15 Yesterday", now=_NOW) == "2026-10-01"


def test_parse_date_garbage_returns_empty():
    assert scraper._parse_date("N/A") == ""
    assert scraper._parse_date("") == ""


def test_parse_amount_range_en_dash():
    assert scraper._parse_amount_range("1K–15K") == (1_000, 15_000)
    assert scraper._parse_amount_range("50K–100K") == (50_000, 100_000)
    assert scraper._parse_amount_range("1M—5M") == (1_000_000, 5_000_000)


def test_live_page_fixture_parses_dates_and_amounts(monkeypatch):
    """Every trade on a real page must come out with dates and a non-zero amount."""
    html = (_Path(__file__).parent.parent / "fixtures" / "capitoltrades_page1_20261002.html").read_text()
    monkeypatch.setattr(scraper, "_get_html", lambda client, page=1, retries=3: html)
    monkeypatch.setattr(scraper, "_now", lambda: _NOW)

    trades = scraper.fetch_trades(pages=1)

    assert trades, "fixture should yield trades"
    for t in trades:
        assert t["traded_date"].startswith("2026-"), t
        assert t["pub_date"] == "2026-10-02", t
        assert t["amount_mid"] > 0, t
