"""AI interpretation via 9Router (primary) and Gemini direct (fallback).

Why both: 9Router is the local AI gateway that fronts multiple models. When
it is down or rate-limited, we fall back to Gemini's public API so users
never see a hard error unless both providers are unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

import requests

from .config import (
    GEMINI_API_KEY,
    GEMINI_API_TIMEOUT,
    GEMINI_CONTINUATION_LIMIT,
    GEMINI_MAX_OUTPUT_TOKENS,
    GEMINI_MODEL,
    GEMINI_TEMPERATURE,
    GEMINI_TOP_P,
    NINE_ROUTER_API_KEY,
    NINE_ROUTER_BASE_URL,
    NINE_ROUTER_ENABLED,
)
from .models import READING_MODES, SPREADS, SpreadType, TarotReading, UserSettings

logger = logging.getLogger(__name__)

# Cap concurrent AI calls to protect 9Router from bursts.
# Sized for typical 9Router capacity (5 simultaneous is safe).
AI_CALL_SEMAPHORE = asyncio.Semaphore(5)


class GeminiTarotInterpreter:
    """Generates tarot interpretations using 9Router or Gemini."""

    def __init__(
        self,
        enabled: bool = True,
        timeout: float = GEMINI_API_TIMEOUT,
        max_output_tokens: int = GEMINI_MAX_OUTPUT_TOKENS,
        continuation_limit: int = GEMINI_CONTINUATION_LIMIT,
        temperature: float = GEMINI_TEMPERATURE,
        top_p: float = GEMINI_TOP_P,
    ):
        self.default_model = GEMINI_MODEL.strip() or "kr/claude-sonnet-4.5"
        self.enabled = enabled
        self.timeout = timeout
        self.max_output_tokens = max(512, max_output_tokens)
        self.continuation_limit = max(0, continuation_limit)
        self.temperature = temperature
        self.top_p = top_p

        # 9Router configuration
        self.use_9router = NINE_ROUTER_ENABLED
        self.base_url = NINE_ROUTER_BASE_URL if self.use_9router else "https://generativelanguage.googleapis.com"

        # Keep BOTH keys so we can fall back when 9Router is down.
        self.ninerouter_key = (NINE_ROUTER_API_KEY or "").strip()
        self.gemini_key = (GEMINI_API_KEY or "").strip()
        if self.use_9router:
            self.api_key = self.ninerouter_key or self.gemini_key
            self.fallback_key = self.gemini_key if self.ninerouter_key else ""
        else:
            self.api_key = self.gemini_key
            self.fallback_key = ""

        # Check if properly configured
        if not self.enabled:
            logger.info("AI interpreter disabled")
        elif not self.api_key:
            logger.warning("API key not configured")
            self.enabled = False
        elif self.use_9router:
            if self.fallback_key:
                logger.info(
                    f"Using 9Router at {self.base_url} (Gemini direct API "
                    f"available as fallback)"
                )
            else:
                logger.info(f"Using 9Router at {self.base_url} (no fallback)")
        else:
            logger.info("Using Gemini API directly")

    def has_fallback(self) -> bool:
        return bool(self.fallback_key)

    def _fallback_model_name(self) -> str:
        model = self.default_model
        if "/" in model:
            return "gemini-2.0-flash"
        return model

    def _get_model_for_user(self, user_id: int) -> str:
        try:
            settings = UserSettings(user_id)
            if settings.ai_model:
                return settings.ai_model
        except Exception as e:
            logger.error(f"Error getting user model: {e}")
        return self.default_model

    def is_configured(self) -> bool:
        return self.enabled and bool(self.api_key)

    def model_label(self, model: str = None) -> str:
        model_name = model or self.default_model
        if self.use_9router:
            return f"9Router ({model_name})"
        return f"Gemini ({model_name})"

    def model_label_for(self, model: str, label: str) -> str:
        if label:
            return f"{label} ({model})"
        return self.model_label(model)

    async def generate_interpretation(self, reading: TarotReading) -> Optional[Tuple[str, bool, str]]:
        if not self.is_configured():
            return None

        model = self._get_model_for_user(reading.user_id)
        prompt = self._build_prompt(reading)
        loop = asyncio.get_running_loop()

        async with AI_CALL_SEMAPHORE:
            attempts: List[Tuple[str, Callable, str, str]] = []
            if self.use_9router and self.ninerouter_key:
                attempts.append(
                    ("9router", self._generate_via_9router_sync, model, "9Router")
                )
            if self.gemini_key:
                fallback_model = self._fallback_model_name()
                attempts.append(
                    ("gemini", self._generate_via_gemini_sync, fallback_model, "Gemini (fallback)")
                )

            last_error: Optional[Exception] = None
            for provider_name, generate_fn, provider_model, label in attempts:
                try:
                    text, was_truncated = await loop.run_in_executor(
                        None, generate_fn, prompt, provider_model
                    )
                    if attempts and (provider_name != attempts[0][0] or len(attempts) > 1):
                        logger.info(
                            f"AI interpretation succeeded via {label} "
                            f"(model={provider_model})"
                        )
                    return text, was_truncated, self.model_label_for(provider_model, label)
                except Exception as e:
                    last_error = e
                    logger.warning(
                        f"AI provider '{provider_name}' failed: {e}. "
                        f"Falling back to next provider."
                        if len(attempts) > 1
                        else f"AI provider '{provider_name}' failed: {e}"
                    )
                    logger.debug(traceback.format_exc())
                    continue

            if last_error:
                logger.error(f"AI interpretation failed on all providers: {last_error}")
            return None

    def _generate_via_9router_sync(self, prompt: str, model: str) -> Tuple[str, bool]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Kamu adalah pembaca tarot reflektif yang hangat dan bijaksana."},
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
        try:
            logger.info(f"Calling 9Router: {url} with model: {model}")
            response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            logger.info(f"9Router response status: {response.status_code}")

            if not response.text or not response.text.strip():
                logger.error("9Router returned empty response")
                raise RuntimeError("9Router returned empty response. Please make sure 9Router is running.")

            try:
                data = response.json()
            except json.JSONDecodeError as e:
                logger.error(f"9Router returned invalid JSON: {response.text[:200]}")
                raise RuntimeError(f"9Router returned invalid JSON: {response.text[:100]}") from e

            response.raise_for_status()

            text = ""
            if "choices" in data and len(data["choices"]) > 0:
                choice = data["choices"][0]
                if "message" in choice and "content" in choice["message"]:
                    text = choice["message"]["content"]
                elif "text" in choice:
                    text = choice["text"]

            if not text and "response" in data:
                text = data["response"]
            if not text and "text" in data:
                text = data["text"]

            was_truncated = False
            if "usage" in data and data["usage"].get("total_tokens", 0) >= self.max_output_tokens:
                was_truncated = True

            if not text:
                logger.warning("9Router returned empty content")
                return "Maaf, 9Router tidak mengembalikan respons yang valid.", was_truncated

            return text.strip(), was_truncated

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Cannot connect to 9Router: {e}")
            raise RuntimeError("9Router tidak berjalan. Jalankan 'npx 9router' terlebih dahulu.") from e
        except requests.exceptions.Timeout as e:
            logger.error(f"9Router timeout: {e}")
            raise RuntimeError("9Router timeout. Periksa apakah 9Router merespons.") from e
        except requests.exceptions.RequestException as e:
            logger.error(f"9Router API error: {e}")
            raise RuntimeError(f"9Router API error: {e}") from e

    def _generate_via_gemini_sync(self, prompt: str, model: str) -> Tuple[str, bool]:
        api_key = self.gemini_key if self.use_9router else self.api_key
        if not api_key:
            raise RuntimeError("Gemini API key not configured for fallback")

        model_path = model if model.startswith("models/") else f"models/{model}"
        encoded_model = urllib.parse.quote(model_path, safe="/")
        encoded_key = urllib.parse.quote(api_key, safe="")
        url = f"https://generativelanguage.googleapis.com/v1beta/{encoded_model}:generateContent?key={encoded_key}"

        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "topP": self.top_p,
                "maxOutputTokens": self.max_output_tokens,
            },
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            ],
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")[:500]
            logger.error(f"Gemini API HTTP {e.code}: {error_body}")
            raise RuntimeError(f"Gemini API returned HTTP {e.code}: {error_body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Gemini API connection error: {e.reason}") from e

        text, was_truncated = self._extract_text_and_truncation(response_data)
        if not text:
            if response_data.get("error"):
                error_msg = response_data["error"].get("message", "Unknown error")
                raise RuntimeError(f"Gemini API error: {error_msg}")
            raise RuntimeError("Gemini API returned an empty response")
        return text.strip(), was_truncated

    @staticmethod
    def _extract_text_and_truncation(response_data: Dict) -> Tuple[str, bool]:
        chunks = []
        was_truncated = False
        for candidate in response_data.get("candidates", []):
            if candidate.get("finishReason") == "MAX_TOKENS":
                was_truncated = True
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                text = part.get("text")
                if text:
                    chunks.append(text)
        return "\n".join(chunks), was_truncated

    @staticmethod
    def _build_continuation_prompt(original_prompt: str, previous_text: str) -> str:
        previous_tail = previous_text[-1800:]
        return (
            "Lanjutkan interpretasi tarot berikut dalam bahasa Indonesia tepat dari bagian yang terputus. "
            "Jangan mengulang dari awal, jangan membuka ulang dengan salam, dan selesaikan bagian yang belum selesai.\n\n"
            "Instruksi dan data reading asli:\n"
            f"{original_prompt}\n\n"
            "Teks yang sudah dibuat sebelumnya, lanjutkan setelah bagian ini:\n"
            f"{previous_tail}"
        )

    def _build_prompt(self, reading: TarotReading) -> str:
        spread_info = SPREADS.get(reading.spread_type, SPREADS[SpreadType.SINGLE.value])
        card_lines = []
        for index, (card, position) in enumerate(zip(reading.cards, reading.positions), start=1):
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