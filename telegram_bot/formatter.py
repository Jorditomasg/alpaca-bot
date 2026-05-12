"""Pure functions that turn event data into Telegram MarkdownV2 strings.

No I/O. All dynamic text passes through escape_md to avoid parse errors.
Code blocks (triple backticks) only need backtick escaping inside.
"""
_RESERVED = r"_*[]()~`>#+-=|{}.!"


def escape_md(s) -> str:
    """Escape MarkdownV2 reserved characters in arbitrary text."""
    out = []
    for ch in str(s):
        if ch in _RESERVED:
            out.append("\\")
        out.append(ch)
    return "".join(out)


def _money(v: float) -> str:
    return escape_md(f"${v:.2f}")


def _pct(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return escape_md(f"{sign}{v:.1f}%")


def format_trade(strategy, side, symbol, qty=None, notional=None, price=None, reason=""):
    strat = strategy.upper()
    side_u = side.upper()
    if notional is not None:
        amt = _money(notional)
    elif qty is not None:
        amt = escape_md(f"{qty:.4f}")
    else:
        amt = "?"
    price_str = _money(price) if price is not None else "?"
    reason_str = escape_md(reason) if reason else ""
    parts = [f"*\\[{strat}\\]* {side_u} {amt} {escape_md(symbol)} @ {price_str}"]
    if reason_str:
        parts.append(f"_{reason_str}_")
    return "\n".join(parts)


def format_state(strategy, event, details: dict):
    strat = strategy.upper()
    if event == "trailing_active":
        return f"*\\[{strat}\\]* Trailing active — floor {_money(details['floor'])}"
    if event == "ladder_fired":
        return (f"*\\[{strat}\\]* {escape_md(details['label'])} @ "
                f"{_money(details['price'])} — bought {_money(details['amount'])}")
    if event == "spread_opened":
        return (f"*\\[{strat}\\]* Spread opened {escape_md(details['symbol'])} "
                f"{_money(details['short_strike'])}/{_money(details['long_strike'])} — "
                f"credit {_money(details['credit'])}")
    if event == "spread_closed":
        return (f"*\\[{strat}\\]* Spread closed @ {_pct(details['profit_pct'])} — "
                f"{_money(details['pnl'])}")
    if event == "follow_change":
        score_str = escape_md(f"{details['score']:.2f}")
        return (f"*\\[{strat}\\]* Now following {escape_md(details['politician'])} "
                f"\\(score {score_str}\\)")
    return f"*\\[{strat}\\]* {escape_md(event)}"


def format_error(task: str, error: str) -> str:
    return f"🚨 *\\[ERROR\\]* {escape_md(task)}: {escape_md(error)}"


def format_warn(scope: str, message: str) -> str:
    return f"⚠️ *\\[{escape_md(scope)}\\]* {escape_md(message)}"


def format_daily_summary(date_str, trailing, copy, wheel, account) -> str:
    """Triple-backtick code block. Inside, only backticks would need escaping."""
    lines = []
    lines.append(f"📊 Daily Summary — {date_str}")
    lines.append("")
    if trailing:
        sign = "+" if trailing['day_pct'] >= 0 else ""
        lines.append(f"Trailing ({trailing['symbol']})")
        lines.append(f"  Position: {trailing['qty']:.4f} sh @ ${trailing['entry']:.2f}")
        lines.append(f"  Floor: ${trailing['floor']:.2f}  |  Today: {sign}{trailing['day_pct']:.1f}%")
        lines.append("")
    if copy:
        sign = "+" if copy['day_pct'] >= 0 else ""
        lines.append(f"Copy (following: {copy.get('following') or '-'})")
        lines.append(f"  Open: {copy['open_count']} positions  |  Today: {sign}{copy['day_pct']:.1f}%")
        lines.append("")
    if wheel:
        sign = "+" if wheel['day_pct'] >= 0 else ""
        lines.append(f"Wheel ({wheel['symbol']})")
        lines.append(f"  Phase: {wheel['stage']}")
        lines.append(f"  Credit collected (week): ${wheel['credit_week']:.2f}")
        lines.append(f"  Today: {sign}{wheel['day_pct']:.1f}%")
        lines.append("")
    if account:
        sign = "+" if account['day_pct'] >= 0 else ""
        lines.append("Account")
        lines.append(f"  Equity: ${account['equity']:,.2f}  ({sign}{account['day_pct']:.1f}% day)")
        lines.append(f"  Buying power: ${account['buying_power']:,.2f}")
    body = "\n".join(lines)
    return f"```\n{body}\n```"
