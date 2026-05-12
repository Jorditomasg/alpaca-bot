from telegram_bot import formatter as f


def test_escape_md_escapes_reserved_chars():
    assert f.escape_md("hello.world") == r"hello\.world"
    assert f.escape_md("a-b") == r"a\-b"
    src = "_*[]()~`>#+-=|{}.!"
    out = f.escape_md(src)
    assert out == "".join(f"\\{c}" for c in src)


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
    assert r"245\.30" in msg
    assert r"Ladder \-22" in msg


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
    assert r"$125\.00" in msg  # $ is not reserved in MarkdownV2, but . is


def test_format_error_has_alarm_prefix():
    msg = f.format_error(task="wheel_task", error="ConnectionRefused")
    assert msg.startswith("🚨")
    assert r"wheel\_task" in msg  # _ is reserved → escaped
    assert "ConnectionRefused" in msg


def test_format_warn_has_warn_prefix():
    msg = f.format_warn(scope="WHEEL", message="Buying power $312 < $400")
    assert msg.startswith("⚠️")
    assert "WHEEL" in msg


def test_format_state_transition():
    msg = f.format_state(
        strategy="trailing",
        event="trailing_active",
        details={"floor": 221.22, "symbol": "TSLA"},
    )
    assert "TRAILING" in msg
    assert r"221\.22" in msg


def test_format_daily_summary_is_code_block():
    rendered = f.format_daily_summary(
        date_str="2026-05-12",
        trailing={"symbol": "TSLA", "qty": 0.12, "entry": 245.30, "floor": 231.22, "day_pct": 1.2},
        copy={"following": "Pelosi", "open_count": 2, "day_pct": 0.4},
        wheel={"symbol": "SOFI", "stage": "SPREAD_OPEN", "credit_week": 1.23, "day_pct": 0.6},
        account={"equity": 10234.5, "day_pct": 0.8, "buying_power": 4512.0},
    )
    assert rendered.startswith("```")
    assert rendered.rstrip().endswith("```")
    assert "TSLA" in rendered
    assert "Pelosi" in rendered
    assert "SPREAD_OPEN" in rendered
