import os
from collections.abc import Awaitable, Callable
from alpaca.data.live import StockDataStream


def start(symbol: str, on_price: Callable[[float], Awaitable[None]]) -> None:
    wss = StockDataStream(
        os.environ["ALPACA_API_KEY"],
        os.environ["ALPACA_SECRET_KEY"],
    )

    async def handler(data):
        await on_price(float(data.price))

    wss.subscribe_trades(handler, symbol)
    print(f"[TRAILING] Streaming {symbol} trades...")
    wss.run()
