"""Shared async / logging helpers."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def safe_task(coro, *, name: str = None) -> asyncio.Task:
    """Schedule a coroutine and attach a done-callback that logs failures.

    ``asyncio.create_task`` swallows exceptions silently unless someone awaits
    the task or attaches a done-callback. For fire-and-forget tasks (reaction
    listeners, firebase sync, etc.) wrap them here so any crash is logged with
    the original traceback instead of vanishing.
    """
    task = asyncio.create_task(coro, name=name)

    def _log_failure(t: asyncio.Task) -> None:
        try:
            t.result()  # raises if the task failed
        except asyncio.CancelledError:
            # Expected when the bot is shutting down — don't spam logs.
            return
        except Exception as e:
            logger.error(
                f"Background task {name or coro!r} crashed: {e}",
                exc_info=e,
            )

    task.add_done_callback(_log_failure)
    return task