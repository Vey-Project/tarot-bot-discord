"""Self-check: chunk_embeds() keeps every batch under Discord's per-message limits.

Discord enforces, per MESSAGE (not per embed):
  - max 10 embeds
  - total of all embeds' characters <= 6000  (error 50035 "Embed size exceeds maximum size of 6000")

Batching embeds into one ctx.send(embeds=[...]) fixed the 40094 follow-up cap but
tripped 6000 for multi-card readings (each detail embed can be ~4096 chars).
chunk_embeds() must split so each batch respects both limits.

Run: PYTHONPATH=. python3 tests/test_chunk_embeds.py
"""
import discord

from bot.utils import chunk_embeds, embed_len


def mk(n):
    return discord.Embed(title="t", description="x" * n)


# one big embed alone -> one batch
b = chunk_embeds([mk(4000)])
assert len(b) == 1 and len(b[0]) == 1, b

# 5 embeds x 4000 chars -> must split into 5 batches (each alone)
b = chunk_embeds([mk(4000) for _ in range(5)])
assert len(b) == 5, [len(x) for x in b]
assert all(sum(embed_len(e) for e in batch) <= 6000 for batch in b)

# 3 x 1900 = 5703 -> fits in one batch; adding a 4th (7604) must spill
b = chunk_embeds([mk(1900) for _ in range(4)])
assert [len(x) for x in b] == [3, 1], [len(x) for x in b]

# 12 tiny embeds -> 10-per-message cap
b = chunk_embeds([mk(5) for _ in range(12)])
assert [len(x) for x in b] == [10, 2], [len(x) for x in b]

# empty in, empty out
assert chunk_embeds([]) == []

# order preserved
es = [mk(10 + i) for i in range(4)]
assert [e for batch in chunk_embeds(es) for e in batch] == es

print("OK: chunk_embeds respects 10-embed and 6000-char per-message limits")
