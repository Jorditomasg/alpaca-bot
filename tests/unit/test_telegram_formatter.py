from telegram_bot import formatter as f


def test_html_escape_basic():
    assert f.html_escape("a<b>c") == "a&lt;b&gt;c"
    assert f.html_escape("a & b") == "a &amp; b"
    assert f.html_escape("normal.text") == "normal.text"


def test_escape_md_is_alias_for_html_escape():
    """Backwards-compat shim."""
    assert f.escape_md("a<b>") == f.html_escape("a<b>")


def test_format_trade_buy():
    msg = f.format_trade(
        strategy="trailing",
        side="buy",
        symbol="TSLA",
        qty=0.12,
        price=245.30,
        reason="Ladder -22%",
    )
    assert "TRAILING" in msg
    assert "BUY" in msg
    assert "TSLA" in msg
    assert "$245.30" in msg
    assert "Ladder -22%" in msg
    assert "<b>[TRAILING]</b>" in msg
    assert "<i>" in msg and "</i>" in msg


def test_format_trade_sell_with_notional():
    msg = f.format_trade(
        strategy="wheel",
        side="sell",
        symbol="SOFI",
        qty=None,
        notional=125.0,
        price=12.5,
        reason="Floor breached",
    )
    assert "SELL" in msg
    assert "$125.00" in msg


def test_format_trade_escapes_symbol():
    """Ticker with HTML-reserved chars must be escaped (paranoia)."""
    msg = f.format_trade(strategy="trailing", side="buy", symbol="A<B>",
                          qty=1, price=1.0)
    assert "A&lt;B&gt;" in msg
    assert "<A" not in msg.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")


def test_format_error_has_alarm_prefix():
    msg = f.format_error(task="wheel_task", error="ConnectionRefused")
    assert msg.startswith("🚨")
    assert "wheel_task" in msg
    assert "ConnectionRefused" in msg
    assert "<b>[ERROR]</b>" in msg


def test_format_warn_has_warn_prefix():
    msg = f.format_warn(scope="WHEEL", message="Buying power $312 < $400")
    assert msg.startswith("⚠️")
    assert "WHEEL" in msg
    assert "&lt;" in msg  # `<` escaped


def test_format_state_transition():
    msg = f.format_state(
        strategy="trailing",
        event="trailing_active",
        details={"floor": 221.22, "symbol": "TSLA"},
    )
    assert "TRAILING" in msg
    assert "$221.22" in msg


def test_format_daily_summary_is_pre_block():
    rendered = f.format_daily_summary(
        date_str="2026-05-12",
        trailing={"symbol": "TSLA", "qty": 0.12, "entry": 245.30, "floor": 231.22, "day_pct": 1.2},
        copy={"following": "Pelosi", "open_count": 2, "day_pct": 0.4},
        wheel={"symbol": "SOFI", "stage": "SPREAD_OPEN", "credit_week": 1.23, "day_pct": 0.6},
        account={"equity": 10234.5, "day_pct": 0.8, "buying_power": 4512.0},
    )
    assert rendered.startswith("<pre>")
    assert rendered.rstrip().endswith("</pre>")
    assert "TSLA" in rendered
    assert "Pelosi" in rendered
    assert "SPREAD_OPEN" in rendered
