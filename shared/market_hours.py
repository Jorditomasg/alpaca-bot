from datetime import datetime, time
import pytz

ET = pytz.timezone("America/New_York")
_OPEN  = time(9, 30)
_CLOSE = time(16, 0)


def now_et() -> datetime:
    return datetime.now(ET)


def is_market_open() -> bool:
    now = now_et()
    if now.weekday() >= 5:
        return False
    return _OPEN <= now.time() <= _CLOSE


def is_market_close() -> bool:
    now = now_et()
    t = now.time()
    return now.weekday() < 5 and time(15, 58) <= t <= time(16, 2)
