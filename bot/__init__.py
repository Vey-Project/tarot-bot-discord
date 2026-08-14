"""Tarot Discord bot — modular package layout.

Public entry point: :func:`run` (also re-exported as ``bot.run``).
The thin ``main.py`` at the project root simply calls :func:`run` so
``python main.py`` keeps working as before.
"""

from __future__ import annotations

from .bot import bot, run
from .config import load_tarot_cards

# Load tarot card definitions eagerly so anything that imports TAROT_CARDS
# gets a populated list. Safe to call multiple times.
load_tarot_cards()

__version__ = "1.1.0"
__all__ = ["bot", "run", "__version__"]