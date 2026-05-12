"""Pure functions that turn event data into Telegram HTML strings.

No I/O. Dynamic text passes through html_escape so user-controlled strings
(symbols, politician names, error messages) cannot break HTML parsing.

HTML parse_mode rules (much simpler than MarkdownV2):
  - escape `<`, `>`, `&` in any user text
  - allowed tags: <b>, <strong>, <i>, <em>, <u>, <s>, <code>, <pre>, <a>
  - everything else (`.`, `+`, `(`, `)`, `|`, `$`, etc.) is literal
"""
import html


def html_escape(s) -> str:
    return html.escape(str(s), quote=False)


def _money(v: float) -> str:
    return f"${v:.2f}"


def _pct(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def format_trade(strategy, side, symbol, qty=None, notional=None, price=None, reason=""):
    strat = strategy.upper()
    side_u = side.upper()
    if notional is not None:
        amt = _money(notional)
    elif qty is not None:
        amt = f"{qty:.4f}"
    else:
        amt = "?"
    price_str = _money(price) if price is not None else "?"
    parts = [f"<b>[{strat}]</b> {side_u} {amt} {html_escape(symbol)} @ {price_str}"]
    if reason:
        parts.append(f"<i>{html_escape(reason)}</i>")
    return "\n".join(parts)


def format_state(strategy, event, details: dict):
    strat = strategy.upper()
    if event == "trailing_active":
        return f"<b>[{strat}]</b> Trailing active — floor {_money(details['floor'])}"
    if event == "ladder_fired":
        return (f"<b>[{strat}]</b> {html_escape(details['label'])} @ "
                f"{_money(details['price'])} — bought {_money(details['amount'])}")
    if event == "spread_opened":
        return (f"<b>[{strat}]</b> Spread opened {html_escape(details['symbol'])} "
                f"{_money(details['short_strike'])}/{_money(details['long_strike'])} — "
                f"credit {_money(details['credit'])}")
    if event == "spread_closed":
        return (f"<b>[{strat}]</b> Spread closed @ {_pct(details['profit_pct'])} — "
                f"{_money(details['pnl'])}")
    if event == "follow_change":
        score_str = f"{details['score']:.2f}"
        return (f"<b>[{strat}]</b> Now following {html_escape(details['politician'])} "
                f"(score {score_str})")
    return f"<b>[{strat}]</b> {html_escape(event)}"


def format_error(task: str, error: str) -> str:
    return f"🚨 <b>[ERROR]</b> {html_escape(task)}: {html_escape(error)}"


def format_warn(scope: str, message: str) -> str:
    return f"⚠️ <b>[{html_escape(scope)}]</b> {html_escape(message)}"


def format_daily_summary(date_str, trailing, copy, wheel, account) -> str:
    """<pre>-wrapped block. Body is html-escaped as a single unit."""
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
    return f"<pre>{html_escape(body)}</pre>"


# ── Backwards-compat shim ───────────────────────────────────────────────────
# Some call sites (e.g. scheduler.py copy_task batch message) imported
# `escape_md` before we switched parse_mode. Alias to html_escape so existing
# imports keep working and produce correct HTML-mode output.
escape_md = html_escape
