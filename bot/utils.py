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


# Discord per-MESSAGE limits (independent of the per-embed 4096/1024 caps).
MAX_EMBEDS_PER_MESSAGE = 10
MAX_EMBED_CHARS_PER_MESSAGE = 6000


def embed_len(embed) -> int:
    """Character count Discord uses for the 6000/message total."""
    total = len(embed.title or "") + len(embed.description or "")
    if embed.footer and embed.footer.text:
        total += len(embed.footer.text)
    if embed.author and embed.author.name:
        total += len(embed.author.name)
    for field in embed.fields:
        total += len(field.name or "") + len(field.value or "")
    return total


def chunk_embeds(embeds, max_embeds: int = MAX_EMBEDS_PER_MESSAGE,
                 max_chars: int = MAX_EMBED_CHARS_PER_MESSAGE):
    """Split embeds into batches each safe for a single ``send(embeds=...)``.

    Sending N embeds in one message is how we stay under the 5-follow-up cap
    (40094), but one message may hold at most 10 embeds and 6000 total chars
    (50035 "Embed size exceeds maximum size of 6000"). Order is preserved.
    """
    batches, current, current_chars = [], [], 0
    for embed in embeds:
        size = embed_len(embed)
        if current and (len(current) >= max_embeds or current_chars + size > max_chars):
            batches.append(current)
            current, current_chars = [], 0
        current.append(embed)
        current_chars += size
    if current:
        batches.append(current)
    return batches