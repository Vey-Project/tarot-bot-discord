"""Self-check: verify the orientation_symbol fix (replaces runtime crash on weekly + _send_card_info).

Run: python3 tests/test_orientation_symbol.py
No framework, no fixture — keeps with the lazy-senior rule.
"""
from bot.models import TarotCard, CardOrientation

c_data = {"name": "The Fool", "number": 0, "arcana": "major",
          "meaning_up": "x", "meaning_rev": "y"}

up = TarotCard(c_data)
rev = TarotCard(c_data, CardOrientation.REVERSED)

assert hasattr(up, "orientation_symbol"), "orientation_symbol missing on upright card"
assert hasattr(rev, "orientation_symbol"), "orientation_symbol missing on reversed card"
assert up.orientation_symbol != rev.orientation_symbol, "symbols should differ"
assert up.orientation_symbol == "⬆️", f"upright symbol wrong: {up.orientation_symbol!r}"
assert rev.orientation_symbol == "🔄", f"reversed symbol wrong: {rev.orientation_symbol!r}"
assert up.orientation_text == "Upright", "orientation_text regressed"
assert rev.orientation_text == "Reversed", "orientation_text regressed"

import ast
ast.parse(open("bot/cog.py").read())
ast.parse(open("bot/models.py").read())

print("OK: orientation_symbol works, AST clean")
