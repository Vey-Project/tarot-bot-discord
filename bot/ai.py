"""AI interpretation via 9Router (the only supported provider).

9Router is the local AI gateway that fronts multiple models. This module
talks to it directly with no fallback: if 9Router is down, the bot shows
the local card explanations only (no scary error banner).
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from typing import Callable, List, Optional, Tuple

import requests

from .config import (
    NINE_ROUTER_API_KEY,
    NINE_ROUTER_BASE_URL,
    NINE_ROUTER_ENABLED,
    NINE_ROUTER_MAX_OUTPUT_TOKENS,
    NINE_ROUTER_API_TIMEOUT,
    NINE_ROUTER_TEMPERATURE,
    NINE_ROUTER_TOP_P,
    NINE_ROUTER_MODEL,
    NINE_ROUTER_MAX_RETRIES,
    NINE_ROUTER_RETRY_BACKOFF,
)
from .models import READING_MODES, SPREADS, SpreadType, TarotReading, UserSettings

logger = logging.getLogger(__name__)

# Cap concurrent AI calls to protect 9Router from bursts.
# Sized for typical 9Router capacity (5 simultaneous is safe).
AI_CALL_SEMAPHORE = asyncio.Semaphore(5)


class NineRouterInterpreter:
    """Generates tarot interpretations via 9Router (OpenAI-compatible API).

    No fallback provider: if 9Router is unreachable or returns garbage,
    the caller is expected to gracefully render the local card explanations
    only. ``generate_interpretation()`` returns ``None`` in that case.
    """

    def __init__(
        self,
        enabled: bool = True,
        timeout: float = NINE_ROUTER_API_TIMEOUT,
        max_output_tokens: int = NINE_ROUTER_MAX_OUTPUT_TOKENS,
        temperature: float = NINE_ROUTER_TEMPERATURE,
        top_p: float = NINE_ROUTER_TOP_P,
        max_retries: int = NINE_ROUTER_MAX_RETRIES,
        retry_backoff: float = NINE_ROUTER_RETRY_BACKOFF,
    ):
        self.default_model = (NINE_ROUTER_MODEL or "").strip() or "kr/claude-sonnet-4.5"
        self.enabled = enabled
        self.timeout = timeout
        self.max_output_tokens = max(512, max_output_tokens)
        self.temperature = temperature
        self.top_p = top_p
        self.max_retries = max(1, max_retries)
        self.retry_backoff = max(0.0, retry_backoff)

        # 9Router configuration
        self.base_url = NINE_ROUTER_BASE_URL.rstrip("/")
        self.api_key = (NINE_ROUTER_API_KEY or "").strip()
        self.use_9router = NINE_ROUTER_ENABLED

        if not self.enabled:
            logger.info("AI interpreter disabled by config")
        elif not self.use_9router:
            logger.warning("NINE_ROUTER_ENABLED is false; AI interpreter disabled")
            self.enabled = False
        elif not self.api_key:
            logger.warning("NINE_ROUTER_API_KEY not configured; AI interpreter disabled")
            self.enabled = False
        elif self.api_key == "sk-9router-default-key":
            logger.warning(
                "NINE_ROUTER_API_KEY is the placeholder default; "
                "set a real key in .env to enable AI interpretation"
            )
            self.enabled = False
        else:
            logger.info(
                f"9Router interpreter ready (model={self.default_model}, "
                f"timeout={self.timeout}s, max_tokens={self.max_output_tokens}, "
                f"retries={self.max_retries})"
            )

    def is_configured(self) -> bool:
        return self.enabled and bool(self.api_key)

    def model_label(self, model: Optional[str] = None) -> str:
        return f"9Router ({model or self.default_model})"

    def _get_model_for_user(self, user_id: int) -> str:
        try:
            settings = UserSettings(user_id)
            if settings.ai_model:
                return settings.ai_model
        except Exception as e:
            logger.error(f"Error getting user model: {e}")
        return self.default_model

    async def generate_interpretation(
        self, reading: TarotReading
    ) -> Optional[Tuple[str, bool, str]]:
        """Returns ``(text, was_truncated, model_label)`` or ``None`` if all
        retries fail. Callers MUST handle ``None`` as "AI not available,
        render local explanations only" — no exception bubbles up.
        """
        if not self.is_configured():
            return None

        model = self._get_model_for_user(reading.user_id)
        prompt = self._build_prompt(reading)
        loop = asyncio.get_running_loop()

        async with AI_CALL_SEMAPHORE:
            last_error: Optional[Exception] = None
            for attempt in range(1, self.max_retries + 1):
                try:
                    text, was_truncated = await loop.run_in_executor(
                        None, self._call_9router_sync, prompt, model
                    )
                    if attempt > 1:
                        logger.info(
                            f"9Router succeeded on attempt {attempt}/{self.max_retries}"
                        )
                    return text, was_truncated, self.model_label(model)
                except Exception as e:
                    last_error = e
                    logger.warning(
                        f"9Router attempt {attempt}/{self.max_retries} failed: {e}"
                    )
                    logger.debug(traceback.format_exc())
                    if attempt < self.max_retries and self.retry_backoff > 0:
                        await asyncio.sleep(self.retry_backoff * attempt)

            logger.error(
                f"9Router interpretation failed after {self.max_retries} attempts; "
                f"last error: {last_error}"
            )
            return None

    def _call_9router_sync(self, prompt: str, model: str) -> Tuple[str, bool]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Kamu adalah pembaca tarot reflektif yang hangat dan bijaksana."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_output_tokens,
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        response = requests.post(
            url, json=payload, headers=headers, timeout=self.timeout
        )

        if not response.text or not response.text.strip():
            raise RuntimeError("9Router returned empty response")

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"9Router returned invalid JSON: {response.text[:100]}"
            ) from e

        response.raise_for_status()

        text = ""
        if isinstance(data, dict):
            choices = data.get("choices") or []
            if choices:
                choice = choices[0]
                message = choice.get("message") or {}
                text = message.get("content") or choice.get("text") or ""
            if not text:
                text = data.get("response") or data.get("text") or ""

        if not text:
            raise RuntimeError("9Router response contained no usable text")

        was_truncated = False
        usage = data.get("usage") or {}
        if isinstance(usage, dict) and usage.get("total_tokens", 0) >= self.max_output_tokens:
            was_truncated = True

        return text.strip(), was_truncated

    def _build_prompt(self, reading: TarotReading) -> str:
        spread_info = SPREADS.get(reading.spread_type, SPREADS[SpreadType.SINGLE.value])
        card_lines = []
        for index, (card, position) in enumerate(
            zip(reading.cards, reading.positions), start=1
        ):
            card_lines.append({
                "index": index,
                "position": position,
                "card": card.name,
                "orientation": card.orientation_text,
                "arcana": card.arcana,
                "suit": card.suit,
                "keywords": card.keywords[:6],
                "meaning": card.meaning,
                "upright_meaning": card.meaning_up,
                "reversed_meaning": card.meaning_rev,
                "description": card.detailed_description or card.description,
            })

        mode_info = READING_MODES.get(reading.mode, READING_MODES["deep"])
        mode_desc = mode_info.get("description", {}).get(reading.language, "Detailed interpretation")
        lang_instruction = "Gunakan bahasa Indonesia yang natural." if reading.language == "id" else "Use natural English."

        reading_payload = {
            "spread": spread_info.get("name", {}).get(reading.language, reading.spread_type),
            "spread_type": reading.spread_type,
            "spread_description": spread_info.get("description", {}).get(reading.language, ""),
            "question": reading.question or "General reading",
            "is_daily": reading.is_daily,
            "is_weekly": reading.is_weekly,
            "mode": reading.mode,
            "mode_description": mode_desc,
            "cards": card_lines,
        }

        mode_instructions = {
            "simple": "Buat interpretasi yang ringkas dan mudah dipahami. Fokus pada inti pesan, tidak perlu terlalu detail." if reading.language == "id" else "Create a concise and easy-to-understand interpretation. Focus on the core message, not too detailed.",
            "deep": "Buat interpretasi yang mendalam dan detail. Analisis setiap kartu dengan teliti, termasuk hubungan antar kartu." if reading.language == "id" else "Create a deep and detailed interpretation. Analyze each card carefully, including relationships between cards.",
            "gentle": "Gunakan nada yang lembut, empatik, dan penuh kasih. Pastikan pesan terasa menghangatkan dan tidak menghakimi." if reading.language == "id" else "Use a gentle, empathetic, and compassionate tone. Ensure the message feels warm and non-judgmental.",
            "direct": "Gunakan nada yang tegas dan lugas. Berikan jawaban yang jelas tanpa bertele-tele." if reading.language == "id" else "Use a firm and straightforward tone. Give clear answers without beating around the bush.",
        }
        mode_instruction = mode_instructions.get(reading.mode, mode_instructions["deep"])

        safety_instruction = ""
        if reading.sensitive_topics:
            safety_instruction = (
                "\n\n⚠️ PENTING: Pertanyaan ini menyentuh topik sensitif. "
                "Ingatkan bahwa ini adalah alat refleksi, bukan nasihat profesional. "
                "Jika menyangkut kesehatan, hukum, atau keselamatan, sarankan konsultasi dengan ahlinya."
                if reading.language == "id" else
                "\n\n⚠️ IMPORTANT: This question touches on sensitive topics. "
                "Remind that this is a reflection tool, not professional advice. "
                "If it involves health, law, or safety, suggest consulting an expert."
            )

        return (
            f"Kamu adalah pembaca tarot reflektif berbahasa {'Indonesia' if reading.language == 'id' else 'English'}. "
            f"Tugasmu membuat interpretasi tarot yang {'hangat, detail, dan mudah dipahami' if reading.language == 'id' else 'warm, detailed, and easy to understand'} "
            f"berdasarkan data kartu berikut.\n\n"
            f"Gaya interpretasi: {mode_instruction}\n\n"
            f"Batasan penting:\n"
            f"- Jelaskan tarot sebagai alat refleksi, bukan ramalan pasti.\n"
            f"- Jangan membuat klaim kepastian tentang masa depan.\n"
            f"- Jika pertanyaan menyentuh kesehatan, hukum, uang besar, keselamatan, atau keputusan berisiko, sarankan konsultasi profesional.\n"
            f"- Jangan menambahkan kartu baru di luar data yang diberikan.\n"
            f"- Jangan meminta data pribadi sensitif.\n"
            f"{safety_instruction}\n\n"
            f"Format jawaban:\n"
            f"**{'Ringkasan Energi' if reading.language == 'id' else 'Energy Summary'}**: 1 paragraf.\n"
            f"**{'Penjelasan per Kartu' if reading.language == 'id' else 'Card Explanations'}**: jelaskan semua kartu satu per satu sesuai posisi, orientasi, dan makna.\n"
            f"**{'Hubungan Antar Kartu' if reading.language == 'id' else 'Card Relationships'}**: jelaskan pola besar yang menghubungkan kartu-kartu tersebut.\n"
            f"**{'Saran Refleksi' if reading.language == 'id' else 'Reflection Advice'}**: 3-5 poin praktis.\n"
            f"**{'Ringkasan Akhir' if reading.language == 'id' else 'Final Summary'}**: "
            f"{'Inti situasi, hal yang perlu diperhatikan, dan langkah kecil yang bisa dilakukan.' if reading.language == 'id' else 'Core situation, what to watch for, and small steps to take.'}\n"
            f"**{'Catatan' if reading.language == 'id' else 'Note'}**: akhiri dengan pengingat singkat bahwa ini bahan refleksi.\n\n"
            f"{lang_instruction} Hindari jawaban terlalu panjang; tetap padat tapi terasa personal.\n\n"
            f"Data reading:\n{json.dumps(reading_payload, ensure_ascii=False, indent=2)}"
        )