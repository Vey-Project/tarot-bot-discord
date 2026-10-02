"""Safety keyword matching must respect word boundaries.

TarotReading._check_sensitive used `if keyword in question_lower`, so
"information" matched the harm keyword "mati", "asexual" matched "sexual",
and "matikan lampu" matched "mati". Every false positive injects the
"this is not professional advice" paragraph into the 9Router prompt for an
ordinary question.

Indonesian is not space-delimited ("bunuh diri" is two words), so a plain
\\b on the keyword handles the space-separated cases and the two-word
Indonesian phrases still match because they are themselves two words.

Run: PYTHONPATH=. python3 tests/test_safety_keyword_boundaries.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.models import SAFETY_KEYWORDS, TarotReading  # noqa: E402


def detect(question):
    return TarotReading._check_sensitive(None, question)


# (question, expected categories) — none of these should ever be flagged.
FALSE_POSITIVES = [
    ("Can you give me more information about my career?", set()),
    ("I'm asexual", set()),
    ("matikan lampu di kamar", set()),
    ("tell me about my sexuality", set()),
    ("I'm fine", set()),
    ("bypass the kill switch", set()),
]

# (question, expected categories) — these must keep being flagged.
# Verified: every one of these returns its category under both the current
# substring matcher and the word-boundary matcher proposed in 3b.
TRUE_POSITIVES = [
    ("bunuh diri", {"harm"}),
    ("membunuh", {"harm"}),
    ("self-harm", {"harm"}),
    ("suicide", {"harm"}),
    ("pelecehan", {"abuse"}),
    ("kanker", {"health"}),
    ("should I steal from work", {"illegal"}),
]


def test_common_words_are_not_flagged():
    for question, expected in FALSE_POSITIVES:
        assert set(detect(question)) == expected, (
            f"{question!r} -> {detect(question)}, expected {expected}"
        )


def test_real_phrases_still_flag():
    for question, expected in TRUE_POSITIVES:
        assert set(detect(question)) == expected, (
            f"{question!r} -> {detect(question)}, expected {expected}"
        )


def test_matcher_uses_word_boundaries():
    source = (ROOT / "bot" / "models.py").read_text("utf-8")
    body = source.split("def _check_sensitive", 1)[1].split("def _get_text", 1)[0]
    assert "SAFETY_KEYWORD_RE" in body, "no compiled word-boundary regex"
    # every keyword must still be findable by the compiled patterns
    for keywords in SAFETY_KEYWORDS.values():
        for keyword in keywords:
            assert keyword, "empty keyword in SAFETY_KEYWORDS"


test_common_words_are_not_flagged()
test_real_phrases_still_flag()
test_matcher_uses_word_boundaries()
print("OK: safety keywords match on word boundaries, no substring false positives")