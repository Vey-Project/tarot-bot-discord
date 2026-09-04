"""Integration check: chunk_embeds() on REAL card data for the largest spreads.

Builds actual TarotReading objects (weekly=5, celtic=10) from the real card
deck and confirms every chunk_embeds() batch is within Discord's per-message
limits — this is what caused the original 50035 crash (real detailed_description
text is long; the previous unchunked `send(embeds=details)` blew past 6000).

Run: PYTHONPATH=. python3 tests/test_real_reading_batches.py
"""
import random

from bot.config import TAROT_CARDS
from bot.models import SPREADS, SpreadType, TarotCard, TarotReading
from bot.utils import chunk_embeds, embed_len

random.seed(0)


def build_reading(spread_key: str) -> TarotReading:
    info = SPREADS[spread_key]
    n = info["cards"]
    cards = [TarotCard(c) for c in random.sample(TAROT_CARDS, n)]
    positions = info["positions"]["id"]
    return TarotReading(
        user_id=1,
        spread_type=spread_key,
        cards=cards,
        positions=positions,
        question="test",
        language="id",
        mode="deep",
    )


for key in (SpreadType.WEEKLY.value, SpreadType.CELTIC_CROSS.value):
    reading = build_reading(key)
    details = reading.to_detail_embeds(page_size=1)
    assert len(details) == SPREADS[key]["cards"], (key, len(details))

    batches = chunk_embeds(details)
    for batch in batches:
        assert len(batch) <= 10, (key, len(batch))
        total = sum(embed_len(e) for e in batch)
        assert total <= 6000, (key, total)

    print(f"{key}: {len(details)} cards -> {len(batches)} batch(es), "
          f"sizes={[sum(embed_len(e) for e in b) for b in batches]}")

print("OK: real card data stays within Discord per-message limits after chunking")
