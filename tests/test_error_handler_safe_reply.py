"""The command error handler must never raise while reporting an error.

bot.log contains "Error in error handler: 400 Bad Request (error code: 10003):
Unknown Channel" — the handler failed on top of the failure it was
reporting. on_command_error issues 7 ctx.send() calls, each guarded only by
except discord.NotFound; 10003 and 10008 arrive as plain HTTPException, so
they escape. Every reply must go through a guard that swallows HTTPException.

Run: PYTHONPATH=. python3 tests/test_error_handler_safe_reply.py
"""
import ast
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import discord  # noqa: E402

from bot.bot import _safe_reply  # noqa: E402


class StubResponse:
    def __init__(self, status, reason):
        self.status, self.reason = status, reason

    def __str__(self):
        return f"{self.status} {self.reason}"


def http_error(status, reason, code, message):
    return discord.HTTPException(
        StubResponse(status, reason), {"code": code, "message": message}
    )


class LiveContext:
    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class DeadContext:
    def __init__(self, error):
        self.error = error

    async def send(self, *args, **kwargs):
        raise self.error


async def main():
    live = LiveContext()
    await _safe_reply(live, "hello", ephemeral=True)
    assert live.sent == [(("hello",), {"ephemeral": True})], live.sent

    for error in (
        http_error(403, "Forbidden", 50001, "Missing Access"),
        http_error(400, "Bad Request", 10003, "Unknown Channel"),
        http_error(404, "Not Found", 10008, "Unknown Message"),
        http_error(400, "Bad Request", 50035, "Invalid Form Body"),
    ):
        await _safe_reply(DeadContext(error), "unreachable")  # must not raise

    # Source guard: no bare ctx.send( left in the handler.
    tree = ast.parse((ROOT / "bot" / "bot.py").read_text("utf-8"))
    handler = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_command_error"
    )
    offenders = [
        sub.lineno for sub in ast.walk(handler)
        if isinstance(sub, ast.Call)
        and isinstance(sub.func, ast.Attribute)
        and sub.func.attr == "send"
        and isinstance(sub.func.value, ast.Name)
        and sub.func.value.id == "ctx"
    ]
    assert not offenders, f"on_command_error still calls ctx.send at lines {offenders}"

    print("OK: error-handler replies survive 10003/10008 (no 'Error in error handler')")


asyncio.run(main())