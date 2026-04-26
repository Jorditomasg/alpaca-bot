"""
Unified entry point. Starts:
  - FastAPI web dashboard  → http://localhost:7080
  - Trailing stop bot      (WebSocket stream)
  - Copy trader            (polls Capitol Trades every 4h)
  - Wheel strategy         (runs every 15min during market hours)
"""
import asyncio
import uvicorn
from dotenv import load_dotenv
load_dotenv()

from web.app import app as web_app
from scheduler import trailing_task, copy_task, wheel_task


async def main():
    print("=" * 56)
    print("  ALPACA BOT  —  starting all systems")
    print("  Dashboard → http://localhost:7080")
    print("=" * 56)

    web_config = uvicorn.Config(
        web_app,
        host="0.0.0.0",
        port=7080,
        log_level="warning",
    )
    web_server = uvicorn.Server(web_config)

    await asyncio.gather(
        web_server.serve(),
        trailing_task(),
        copy_task(),
        wheel_task(),
    )


if __name__ == "__main__":
    asyncio.run(main())
