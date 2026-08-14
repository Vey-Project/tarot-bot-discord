"""Domain models, enums, and lookup tables.

Anything that is "pure data + simple behavior" lives here. This file has no
Discord or HTTP imports so it can be reused in tests.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional

from .config import (
    DEFAULT_LANGUAGE,
    DEFAULT_READING_MODE,
    GEMINI_ENABLED,
    GEMINI_MODEL,
    SETTINGS_DIR,
)

logger = logging.getLogger(__name__)


# ============================================================
# ENUMS
# ============================================================
class CardOrientation(Enum):
    UPRIGHT = "upright"
    REVERSED = "reversed"


class SpreadType(Enum):
    SINGLE = "single"
    THREE_CARD = "three"
    CELTIC_CROSS = "celtic"
    RELATIONSHIP = "relationship"
    CAREER = "career"
    YESNO = "yesno"
    DAILY = "daily"
    WEEKLY = "weekly"
    LOVE = "love"
    DECISION = "decision"
    SELFCARE = "selfcare"
    SHADOW = "shadow"


# ============================================================
# LOOKUP TABLES
# ============================================================
SPREADS: Dict[str, Dict] = {
    SpreadType.SINGLE.value: {
        "name": {"id": "Kartu Tunggal", "en": "Single Card"},
        "positions": {"id": ["Panduan"], "en": ["Guidance"]},
        "description": {"id": "Wawasan cepat atau panduan harian", "en": "Quick insight or daily guidance"},
        "cards": 1,
        "layout": [[0, 0]],
        "color": 0x3498db,
    },
    SpreadType.THREE_CARD.value: {
        "name": {"id": "Masa Lalu-Sekarang-Masa Depan", "en": "Past-Present-Future"},
        "positions": {"id": ["Masa Lalu", "Sekarang", "Masa Depan"], "en": ["Past", "Present", "Future"]},
        "description": {"id": "Pahami aliran waktu dan energi", "en": "Understand the flow of time and energy"},
        "cards": 3,
        "layout": [[-1, 0], [0, 0], [1, 0]],
        "color": 0x2ecc71,
    },
    SpreadType.CELTIC_CROSS.value: {
        "name": {"id": "Salib Celtic", "en": "Celtic Cross"},
        "positions": {"id": [
            "Situasi Sekarang", "Tantangan", "Pengaruh Masa Lalu",
            "Pengaruh Masa Depan", "Atas (Sadar)", "Bawah (Bawah Sadar)",
            "Saran", "Pengaruh Eksternal", "Harapan/Ketakutan", "Hasil",
        ], "en": [
            "Present Situation", "Challenge", "Past Influences",
            "Future Influences", "Above (Conscious)", "Below (Subconscious)",
            "Advice", "External Influences", "Hopes/Fears", "Outcome",
        ]},
        "description": {"id": "Pembacaan hidup komprehensif (10 kartu)", "en": "Comprehensive life reading (10 cards)"},
        "cards": 10,
        "layout": [
            [0, 0], [1, 0], [-1, 0], [2, 0], [0, 1], [0, -1],
            [-2, -1], [2, -1], [-2, 1], [2, 1],
        ],
        "color": 0xe74c3c,
    },
    SpreadType.RELATIONSHIP.value: {
        "name": {"id": "Wawasan Hubungan", "en": "Relationship Insight"},
        "positions": {"id": ["Kamu", "Pasangan", "Koneksi", "Tantangan", "Potensi"], "en": ["You", "Partner", "Connection", "Challenges", "Potential"]},
        "description": {"id": "Pendalaman dinamika hubungan", "en": "Deep dive into relationship dynamics"},
        "cards": 5,
        "layout": [[-2, 0], [2, 0], [0, 0], [-1, -1], [1, -1]],
        "color": 0x9b59b6,
    },
    SpreadType.CAREER.value: {
        "name": {"id": "Jalur Karir", "en": "Career Path"},
        "positions": {"id": ["Peran Saat Ini", "Kekuatan", "Peluang", "Hambatan", "Saran", "Hasil"], "en": ["Current Role", "Strengths", "Opportunities", "Obstacles", "Advice", "Outcome"]},
        "description": {"id": "Panduan untuk pertumbuhan profesional", "en": "Guidance for professional growth"},
        "cards": 6,
        "layout": [[0, 0], [-1, 1], [1, 1], [-1, -1], [1, -1], [0, 2]],
        "color": 0xf39c12,
    },
    SpreadType.YESNO.value: {
        "name": {"id": "Panduan Ya/Tidak", "en": "Yes/No Guidance"},
        "positions": {"id": ["Jawaban", "Mengapa", "Fokus"], "en": ["Answer", "Why", "Focus"]},
        "description": {"id": "Arahan jelas untuk pertanyaan ya/tidak", "en": "Clear direction for yes/no questions"},
        "cards": 3,
        "layout": [[0, 0], [-1, 1], [1, 1]],
        "color": 0x1abc9c,
    },
    SpreadType.WEEKLY.value: {
        "name": {"id": "Pekanan", "en": "Weekly"},
        "positions": {"id": ["Tema", "Tantangan", "Dukungan", "Saran", "Hasil"], "en": ["Theme", "Challenge", "Support", "Advice", "Outcome"]},
        "description": {"id": "Panduan untuk minggu ini (5 kartu)", "en": "Guidance for the week (5 cards)"},
        "cards": 5,
        "layout": [[0, 0], [-1, 1], [1, 1], [-1, -1], [1, -1]],
        "color": 0x2ecc71,
    },
    SpreadType.LOVE.value: {
        "name": {"id": "Cinta", "en": "Love"},
        "positions": {"id": ["Dirimu", "Pasangan", "Dinamika", "Tantangan", "Harapan", "Hasil"], "en": ["Yourself", "Partner", "Dynamics", "Challenges", "Hopes", "Outcome"]},
        "description": {"id": "Wawasan tentang hubungan cinta (6 kartu)", "en": "Insights about love relationships (6 cards)"},
        "cards": 6,
        "layout": [[-1, 0], [1, 0], [0, 0], [-1, -1], [1, -1], [0, 1]],
        "color": 0xe74c3c,
    },
    SpreadType.DECISION.value: {
        "name": {"id": "Keputusan", "en": "Decision"},
        "positions": {"id": ["Situasi", "Pilihan A", "Pilihan B", "Saran", "Hasil"], "en": ["Situation", "Option A", "Option B", "Advice", "Outcome"]},
        "description": {"id": "Membantu pengambilan keputusan (5 kartu)", "en": "Help with decision making (5 cards)"},
        "cards": 5,
        "layout": [[0, 0], [-1, 1], [1, 1], [-1, -1], [1, -1]],
        "color": 0x3498db,
    },
    SpreadType.SELFCARE.value: {
        "name": {"id": "Perawatan Diri", "en": "Self-Care"},
        "positions": {"id": ["Kebutuhan", "Sumber Daya", "Hambatan", "Tindakan", "Hasil"], "en": ["Needs", "Resources", "Obstacles", "Action", "Outcome"]},
        "description": {"id": "Fokus pada kesejahteraan diri (5 kartu)", "en": "Focus on personal well-being (5 cards)"},
        "cards": 5,
        "layout": [[0, 0], [-1, 1], [1, 1], [-1, -1], [1, -1]],
        "color": 0x9b59b6,
    },
    SpreadType.SHADOW.value: {
        "name": {"id": "Bayangan Diri", "en": "Shadow Work"},
        "positions": {"id": ["Bayangan", "Akar", "Hadapi", "Integrasi", "Kebijaksanaan"], "en": ["Shadow", "Root", "Face", "Integration", "Wisdom"]},
        "description": {"id": "Menjelajahi sisi gelap diri (5 kartu)", "en": "Exploring the dark side of self (5 cards)"},
        "cards": 5,
        "layout": [[0, 0], [-1, 1], [1, 1], [-1, -1], [1, -1]],
        "color": 0x2c3e50,
    },
}

READING_MODES: Dict[str, Dict] = {
    "simple": {
        "id": "Ringkas",
        "en": "Simple",
        "description": {"id": "Interpretasi singkat dan mudah dipahami", "en": "Brief and easy to understand interpretation"},
    },
    "deep": {
        "id": "Mendalam",
        "en": "Deep",
        "description": {"id": "Interpretasi mendalam dan penuh nuansa", "en": "Deep and nuanced interpretation"},
    },
    "gentle": {
        "id": "Lembut",
        "en": "Gentle",
        "description": {"id": "Interpretasi dengan pendekatan lembut", "en": "Soft and supportive interpretation"},
    },
    "direct": {
        "id": "Langsung",
        "en": "Direct",
        "description": {"id": "Interpretasi to-the-point dan jelas", "en": "Direct and clear interpretation"},
    },
}

SAFETY_KEYWORDS: Dict[str, List[str]] = {
    "harm": ["bunuh diri", "suicide", "menyakiti diri", "self-harm", "mati", "killed", "membunuh"],
    "abuse": ["pelecehan", "abuse", "kekerasan", "violence", "kdrt", "sexual"],
    "health": ["cancer", "kanker", "stroke", "schizophrenia", "skizofrenia"],
    "illegal": ["drugs", "narkoba", "hack", "bobol", "curi", "steal"],
}


# ============================================================
# SETTINGS MODELS
# ============================================================
class UserSettings:
    """Manage user settings including AI model selection."""

    def __init__(self, user_id: int, on_change: Optional[Callable[[int], None]] = None):
        self.user_id = user_id
        self.settings_path = SETTINGS_DIR / f"user_{user_id}.json"
        self.language = DEFAULT_LANGUAGE
        self.reading_mode = DEFAULT_READING_MODE
        self.ai_enabled = GEMINI_ENABLED
        self.ai_model = GEMINI_MODEL
        self._on_change = on_change
        self._load()

    def _load(self):
        if self.settings_path.exists():
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.language = data.get("language", DEFAULT_LANGUAGE)
                self.reading_mode = data.get("reading_mode", DEFAULT_READING_MODE)
                self.ai_enabled = data.get("ai_enabled", GEMINI_ENABLED)
                self.ai_model = data.get("ai_model", GEMINI_MODEL)
            except Exception as e:
                logger.error(f"Error loading user settings: {e}")

    def save(self):
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump({
                    "user_id": self.user_id,
                    "language": self.language,
                    "reading_mode": self.reading_mode,
                    "ai_enabled": self.ai_enabled,
                    "ai_model": self.ai_model,
                    "updated_at": datetime.now().isoformat(),
                }, f, indent=2, ensure_ascii=False)
            if self._on_change is not None:
                try:
                    self._on_change(self.user_id)
                except Exception as e:
                    logger.error(f"on_change callback failed for user {self.user_id}: {e}")
        except Exception as e:
            logger.error(f"Error saving user settings: {e}")

    def get_lang(self) -> str:
        return self.language

    def set_language(self, lang: str) -> bool:
        # Lazy import to avoid circular import with bot_i18n.
        from bot_i18n import is_supported
        if is_supported(lang):
            self.language = lang
            self.save()
            return True
        return False

    def get_mode(self) -> str:
        return self.reading_mode

    def set_mode(self, mode: str) -> bool:
        if mode in READING_MODES:
            self.reading_mode = mode
            self.save()
            return True
        return False

    def is_ai_enabled(self) -> bool:
        return self.ai_enabled and GEMINI_ENABLED

    def set_ai_enabled(self, enabled: bool):
        self.ai_enabled = enabled
        self.save()

    def get_ai_model(self) -> str:
        return self.ai_model or GEMINI_MODEL

    def set_ai_model(self, model: str) -> bool:
        self.ai_model = model
        self.save()
        return True


class ServerSettings:
    """Per-guild overrides: language, AI toggle, default channels."""

    def __init__(self, guild_id: int, on_change: Optional[Callable[[int], None]] = None):
        self.guild_id = guild_id
        self.settings_path = SETTINGS_DIR / f"server_{guild_id}.json"
        self.prefix = "!"
        self.language = DEFAULT_LANGUAGE
        self.ai_enabled = GEMINI_ENABLED
        self.reading_channel = None
        self.daily_channel = None
        self._on_change = on_change
        self._load()

    def _load(self):
        if self.settings_path.exists():
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.prefix = data.get("prefix", "!")
                self.language = data.get("language", DEFAULT_LANGUAGE)
                self.ai_enabled = data.get("ai_enabled", GEMINI_ENABLED)
                self.reading_channel = data.get("reading_channel")
                self.daily_channel = data.get("daily_channel")
            except Exception as e:
                logger.error(f"Error loading server settings: {e}")

    def save(self):
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump({
                    "guild_id": self.guild_id,
                    "prefix": self.prefix,
                    "language": self.language,
                    "ai_enabled": self.ai_enabled,
                    "reading_channel": self.reading_channel,
                    "daily_channel": self.daily_channel,
                    "updated_at": datetime.now().isoformat(),
                }, f, indent=2, ensure_ascii=False)
            if self._on_change is not None:
                try:
                    self._on_change(self.guild_id)
                except Exception as e:
                    logger.error(f"on_change callback failed for guild {self.guild_id}: {e}")
        except Exception as e:
            logger.error(f"Error saving server settings: {e}")

    def get_lang(self) -> str:
        return self.language

    def is_ai_enabled(self) -> bool:
        return self.ai_enabled and GEMINI_ENABLED


# ============================================================
# READING MODELS
# ============================================================
class TarotCard:
    """One card with its meanings, orientation, and metadata."""

    def __init__(self, card_data: Dict, orientation: CardOrientation = CardOrientation.UPRIGHT):
        self.data = card_data
        self.orientation = orientation
        self.name = card_data.get("name", "Unknown Card")
        self.number = card_data.get("number", 0)
        self.arcana = card_data.get("arcana", "major")
        self.suit = card_data.get("suit")
        self.keywords = card_data.get("keywords", [])
        self.meaning_up = card_data.get("meaning_up", "No meaning available")
        self.meaning_rev = card_data.get("meaning_rev", "No meaning available")
        self.description = card_data.get("description", "")
        self.detailed_description = card_data.get("detailed_description", self.description)

    @property
    def is_major(self) -> bool:
        return self.arcana == "major"

    @property
    def is_reversed(self) -> bool:
        return self.orientation == CardOrientation.REVERSED

    @property
    def orientation_text(self) -> str:
        return "Reversed" if self.is_reversed else "Upright"

    @property
    def meaning(self) -> str:
        return self.meaning_rev if self.is_reversed else self.meaning_up

    @property
    def image_paths(self) -> List:
        from .config import IMAGES_DIR
        safe_name = self.name.lower().replace(" ", "_").replace("_of_", "_")
        base_name = safe_name.replace("the_", "")
        patterns = [
            f"{self.number:02d}_{safe_name}.jpg",
            f"{self.number:02d}_{safe_name}.jpeg",
            f"{self.number:02d}_{safe_name}.png",
            f"{safe_name}.jpg",
            f"{safe_name}.jpeg",
            f"{safe_name}.png",
            f"{base_name}.jpg",
            f"{base_name}.png",
            f"{self.name.replace(' ', '').replace('_', '').lower()}.jpg",
        ]
        return [IMAGES_DIR / pattern for pattern in patterns]

    @property
    def image_exists(self) -> bool:
        return any(path.exists() for path in self.image_paths)

    def get_image_path(self):
        for path in self.image_paths:
            if path.exists():
                return path
        return None

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "number": self.number,
            "arcana": self.arcana,
            "suit": self.suit,
            "orientation": self.orientation.value,
            "keywords": self.keywords[:5],
        }


class TarotReading:
    """A complete reading: cards, positions, mode, history-relevant fields."""

    def __init__(
        self,
        user_id: int,
        spread_type: str,
        cards: List[TarotCard],
        positions: List[str],
        question: str = None,
        is_daily: bool = False,
        is_weekly: bool = False,
        language: str = "id",
        mode: str = "deep",
        is_favourite: bool = False,
    ):
        self.user_id = user_id
        self.spread_type = spread_type
        self.cards = cards
        self.positions = positions
        self.question = question
        self.is_daily = is_daily
        self.is_weekly = is_weekly
        self.language = language
        self.mode = mode
        self.is_favourite = is_favourite
        self.timestamp = datetime.now()
        self.reading_id = f"{user_id}_{int(self.timestamp.timestamp())}"
        self._spread_info = SPREADS.get(spread_type, SPREADS[SpreadType.SINGLE.value])
        self.sensitive_topics = self._check_sensitive(question)

    def _check_sensitive(self, question: str) -> List[str]:
        if not question:
            return []
        detected = []
        question_lower = question.lower()
        for category, keywords in SAFETY_KEYWORDS.items():
            for keyword in keywords:
                if keyword in question_lower:
                    detected.append(category)
                    break
        return detected

    def _get_text(self, translations: Dict) -> str:
        if self.language in translations:
            return translations[self.language]
        return translations.get("en", "")

    def to_history_entry(self) -> Dict:
        return {
            "reading_id": self.reading_id,
            "timestamp": self.timestamp.isoformat(),
            "spread_type": self.spread_type,
            "question": self.question,
            "cards_count": len(self.cards),
            "language": self.language,
            "mode": self.mode,
            "favourite": self.is_favourite,
        }

    @staticmethod
    def _shorten(text: str, limit: int = 950) -> str:
        if not text:
            return "No description available."
        normalized = " ".join(str(text).split())
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit - 3].rstrip() + "..."
