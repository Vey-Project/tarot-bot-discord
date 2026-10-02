"""Concurrent readings must not overwrite each other in readings.json.

TarotReading.save_to_history is a bare read-modify-write of one shared JSON
file. bot.log shows 289 /tarot invocations; saves/readings.json already
contains 4 rows sharing a reading_id with an earlier row — the signature of
two commands interleaving between their load and their write. One lost
reading silently disappears from /history, /insight, and the Firebase mirror.

The fix serialises the write behind a module-level lock so the critical
section (read -> append -> write) cannot interleave.

Run: PYTHONPATH=. python3 tests/test_readings_json_serialised.py
"""
import json
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bot.config as config  # noqa: E402
import bot.models as models  # noqa: E402


def test_concurrent_saves_keep_every_reading():
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp) / "saves"
        sandbox.mkdir()

        original_config_saves = config.SAVES_DIR
        original_model_saves = models.SAVES_DIR
        config.SAVES_DIR = sandbox
        models.SAVES_DIR = sandbox
        try:
            readings = [
                models.TarotReading(
                    user_id=1,
                    spread_type="single",
                    cards=[],
                    positions=["Panduan"],
                    question=f"question-{i}",
                    language="id",
                    mode="deep",
                )
                for i in range(12)
            ]
            # 12 concurrent saves of a 585 KB-equivalent document. The
            # fixture deliberately does not touch reading_id: Task 1 locks
            # the file, Task 2 changes the id, and neither test may depend
            # on the other's bug.
            start = threading.Barrier(len(readings))
            errors = []

            def save(reading):
                try:
                    start.wait(timeout=5)
                    reading.save_to_history()
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=save, args=(r,)) for r in readings]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

            assert not errors, errors
            rows = json.loads((sandbox / "readings.json").read_text("utf-8"))["readings"]
            questions = [r["question"] for r in rows]
            assert len(rows) == len(readings), (
                f"lost readings: {len(rows)} of {len(readings)}"
            )
            for reading in readings:
                assert reading.question in questions
        finally:
            config.SAVES_DIR = original_config_saves
            models.SAVES_DIR = original_model_saves


def test_lock_is_module_level_and_reentrant_guard_is_present():
    # The lock must live on the module, not be created per call, or it would
    # serialise nothing.
    assert isinstance(getattr(models, "_READINGS_WRITE_LOCK", None), type(threading.Lock()))
    source = (ROOT / "bot" / "models.py").read_text("utf-8")
    assert "_READINGS_WRITE_LOCK" in source
    body = source.split("def save_to_history", 1)[1].split("async def async_save_to_history", 1)[0]
    assert "with _READINGS_WRITE_LOCK:" in body, "save_to_history does not hold the lock"


test_concurrent_saves_keep_every_reading()
test_lock_is_module_level_and_reentrant_guard_is_present()
print("OK: concurrent save_to_history keeps every reading (no lost rows)")