"""reading_id must be unique even when two readings land in the same second.

models.py built reading_id from int(timestamp), so two readings by the same
user inside one second share an id. That silently breaks /favourite (toggles
both rows), /share (ambiguous prefix match), and the Firebase doc id (the
second write is skipped as "already present").

saves/readings.json already has 4 rows sharing an id with an earlier row.

Run: PYTHONPATH=. python3 tests/test_reading_id_unique.py
"""
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bot.config as config  # noqa: E402
import bot.models as models  # noqa: E402


def make(user_id=7, question="q"):
    return models.TarotReading(
        user_id=user_id, spread_type="single", cards=[],
        positions=["Panduan"], question=question, language="id", mode="deep",
    )


def test_same_second_readings_get_distinct_ids():
    stamps = [1700000000.0, 1700000000.0, 1700000000.5, 1700000000.9]

    made = []
    for index, stamp in enumerate(stamps):
        reading = make(question=f"q{index}")
        # Force the collision the fixture is meant to reproduce.
        object.__setattr__(reading, "timestamp", datetime.fromtimestamp(stamp))
        made.append(reading)

    ids = [r.reading_id for r in made]
    assert len(set(ids)) == len(ids), f"collision: {ids}"


def test_existing_saved_rows_are_not_overwritten():
    """Saving two same-second readings must leave two rows on disk."""
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp) / "saves"
        sandbox.mkdir()
        original_config, original_model = config.SAVES_DIR, models.SAVES_DIR
        config.SAVES_DIR = sandbox
        models.SAVES_DIR = sandbox
        try:
            stamp = datetime.fromtimestamp(1700000000.0)
            for index in range(3):
                reading = make(question=f"q{index}")
                object.__setattr__(reading, "timestamp", stamp)
                reading.save_to_history()
            rows = json.loads(
                (sandbox / "readings.json").read_text("utf-8")
            )["readings"]
            assert len(rows) == 3, f"rows lost: {len(rows)}"
            assert len({r['reading_id'] for r in rows}) == 3, "ids collided on disk"
        finally:
            config.SAVES_DIR, models.SAVES_DIR = original_config, original_model


test_same_second_readings_get_distinct_ids()
test_existing_saved_rows_are_not_overwritten()
print("OK: reading_id is unique within the same second")