"""Self-check: embeds must be sent as batched messages, never one follow-up per embed.

Regression guard for the Discord 40094 "This interaction has hit the maximum
number of follow up messages" crash (see CHANGELOG [Unreleased]).

    for e in ...:
        await ctx.send(embed=e)          # one follow-up per embed  -> 40094
    await ctx.send(embeds=[...])         # one message, <=10 embeds  -> safe

While a slash interaction token is alive (15 min), ctx.send() inside command
and reaction flows is a webhook follow-up — capped. Any `await <x>.send(embed=..)`
inside a `for` loop is the bug pattern.

Run: python3 tests/test_batched_sends.py
No framework, no fixture — keeps with the lazy-senior rule.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["bot/cog.py", "bot/bot.py"]


def find_loop_embed_sends(tree):
    """Return {lineno: source-agnostic label} for `await x.send(embed=...)` inside loops."""
    offenders = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.AsyncFor)):
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Await):
                    continue
                call = sub.value
                if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
                    continue
                if call.func.attr != "send":
                    continue
                for kw in call.keywords:
                    if kw.arg == "embed":  # single-embed kwarg; 'embeds' (batched) is fine
                        offenders[sub.lineno] = f"{call.func.attr}(embed=...) in loop"
                        break
    return offenders


failures = {}
for rel in FILES:
    path = ROOT / rel
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = find_loop_embed_sends(tree)
    if found:
        lines = path.read_text(encoding="utf-8").splitlines()
        failures[rel] = {ln: lines[ln - 1].strip() for ln in sorted(found)}

if failures:
    for rel, hits in failures.items():
        for ln, src in hits.items():
            print(f"FAIL {rel}:{ln}: {src}")
    print(f"\n{sum(len(h) for h in failures.values())} per-embed send loop(s) found — batch with embeds=[...] instead.")
    sys.exit(1)

print("OK: no per-embed send loops (40094 regression guard clean)")
