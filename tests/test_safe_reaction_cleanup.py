"""Regression guard: no raw reaction-message mutations that crash on deleted messages.

Discord error 10008 "Unknown Message" fires whenever a reaction-driven message
(menu / reading / card-flip / pagination) was deleted by the user while the bot
waits on `wait_for('reaction_add')`, and the cleanup path then calls a raw
`msg.clear_reactions()`, `msg.remove_reaction(...)`, or `msg.edit(...)` that
only catches `Forbidden` — `NotFound` (a subclass of HTTPException) slips
through and crashes the whole command.

All such mutations must go through the `_safe_*` helpers on `TarotSystem`
(`_safe_clear_reactions`, `_safe_remove_reaction`, `_safe_edit_message`), which
swallow `(Forbidden, HTTPException)`.

Run: python3 tests/test_safe_reaction_cleanup.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COG = ROOT / "bot" / "cog.py"

TARGETS = ("clear_reactions", "remove_reaction")
ALLOWED_HELPERS = {"_safe_clear_reactions", "_safe_remove_reaction", "_safe_edit_message"}

source = COG.read_text()
tree = ast.parse(source)

# Only look at method bodies, and exclude the _safe_* helper bodies themselves.
bad = []
helper_names = set()

for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("_safe_"):
        helper_names.add(node.name)

for node in ast.walk(tree):
    if not isinstance(node, ast.AsyncFunctionDef):
        continue
    # skip the helper bodies
    if node.name in ALLOWED_HELPERS:
        continue
    # skip if this method is not defined on TarotSystem — but scanning any class
    # method is fine; the constraint is universal for reaction mutations.
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn = sub.func
            if isinstance(fn, ast.Attribute) and fn.attr in TARGETS:
                bad.append((node.name, sub.lineno, fn.attr))

if bad:
    for name, lineno, attr in bad:
        print(f"{name} (line {lineno}): raw .{attr}() — use _safe_* helper")
    sys.exit(1)

print("OK: no raw clear_reactions/remove_reaction outside _safe_* helpers (10008 guard clean)")
