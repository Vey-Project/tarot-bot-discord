"""Thin entry point — the heavy lifting now lives in the ``bot`` package.

Run with: ``python main.py`` (loads .env, then calls bot.run()).
"""

from dotenv import load_dotenv

# Load .env BEFORE the bot package is imported so config picks up env vars.
load_dotenv()

from bot import run

if __name__ == "__main__":
    run()