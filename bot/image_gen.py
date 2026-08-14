"""Card image generation.

Two strategies:
1. If a real card image exists in ``images/`` → load, optionally rotate 180°
   for reversed cards, and overlay an orientation indicator.
2. Otherwise → render a stylised fallback card using PIL primitives so the
   bot still has something visually useful even without the asset library.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont

from .models import TarotCard

logger = logging.getLogger(__name__)


class CardImageGenerator:
    """Stateless renderer; everything is class-level for ergonomics."""

    SUIT_COLORS = {
        "wands": {"bg": (180, 60, 30), "fg": (255, 220, 180), "accent": (255, 215, 0)},
        "cups": {"bg": (30, 60, 150), "fg": (200, 220, 255), "accent": (192, 255, 255)},
        "swords": {"bg": (60, 60, 90), "fg": (220, 220, 255), "accent": (220, 220, 255)},
        "pentacles": {"bg": (50, 100, 30), "fg": (220, 255, 200), "accent": (255, 215, 0)},
        None: {"bg": (20, 10, 40), "fg": (220, 180, 255), "accent": (255, 215, 0)},
    }

    SUIT_SYMBOLS = {
        "wands": "🜂",
        "cups": "🜄",
        "swords": "🜁",
        "pentacles": "🜃",
    }

    @classmethod
    def generate_card_image(cls, card: TarotCard, size: Tuple[int, int] = (400, 600)) -> io.BytesIO:
        try:
            img_path = card.get_image_path()
            if img_path:
                return cls._load_and_modify_image(img_path, card, size)
            return cls._generate_fallback_image(card, size)
        except Exception as e:
            logger.error(f"Error generating image for {card.name}: {e}")
            return cls._generate_simple_image(card, size)

    @classmethod
    def _load_and_modify_image(cls, img_path: Path, card: TarotCard, size: Tuple[int, int]) -> io.BytesIO:
        img = Image.open(img_path)
        img = img.convert("RGB")
        if img.size != size:
            img = img.resize(size, Image.Resampling.LANCZOS)
        if card.is_reversed:
            img = img.rotate(180)
        draw = ImageDraw.Draw(img)
        indicator = "🔄" if card.is_reversed else "⬆️"
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        bbox = draw.textbbox((0, 0), indicator, font=ImageFont.load_default(20))
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        rect_pos = (10, 10, 10 + text_width + 10, 10 + text_height + 10)
        overlay_draw.rounded_rectangle(rect_pos, radius=5, fill=(0, 0, 0, 180))
        img = Image.alpha_composite(img.convert("RGBA"), overlay)
        draw = ImageDraw.Draw(img)
        draw.text((20, 15), indicator, fill=(255, 255, 255), font=ImageFont.load_default(20))
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG", quality=85)
        img_bytes.seek(0)
        return img_bytes

    @classmethod
    def _generate_fallback_image(cls, card: TarotCard, size: Tuple[int, int]) -> io.BytesIO:
        width, height = size
        colors = cls.SUIT_COLORS.get(card.suit, cls.SUIT_COLORS[None])
        img = Image.new("RGB", (width, height), colors["bg"])
        draw = ImageDraw.Draw(img)

        border_width = 15
        draw.rectangle(
            [border_width, border_width, width - border_width, height - border_width],
            outline=colors["accent"], width=3,
        )

        corner_size = 40
        for corner in [(0, 0), (width, 0), (0, height), (width, height)]:
            x, y = corner
            if x == 0 and y == 0:
                points = [(0, 0), (corner_size, 0), (0, corner_size)]
            elif x == width and y == 0:
                points = [(width, 0), (width - corner_size, 0), (width, corner_size)]
            elif x == 0 and y == height:
                points = [(0, height), (corner_size, height), (0, height - corner_size)]
            else:
                points = [(width, height), (width - corner_size, height), (width, height - corner_size)]
            draw.polygon(points, fill=colors["accent"])

        title_font = ImageFont.load_default(24)
        draw.text((width // 2, 60), card.name.upper(), fill=colors["fg"],
                 font=title_font, anchor="mm")

        if card.suit:
            suit_symbol = cls.SUIT_SYMBOLS.get(card.suit, "•")
            suit_text = f"{suit_symbol} {card.suit.title()} {suit_symbol}"
            draw.text((width // 2, 100), suit_text, fill=colors["accent"],
                     font=ImageFont.load_default(18), anchor="mm")

        arcana_text = f"{card.arcana.upper()} ARCANA"
        draw.text((width // 2, 130), arcana_text, fill=(200, 200, 255),
                 font=ImageFont.load_default(16), anchor="mm")

        orient_color = (255, 100, 100) if card.is_reversed else (100, 255, 100)
        orient_text = "REVERSED" if card.is_reversed else "UPRIGHT"
        draw.rectangle([width // 2 - 70, 160, width // 2 + 70, 190], fill=orient_color)
        draw.text((width // 2, 175), orient_text, fill=(0, 0, 0),
                 font=ImageFont.load_default(18), anchor="mm")

        keywords = card.keywords[:4]
        keyword_y = 220
        for keyword in keywords:
            draw.text((width // 2, keyword_y), f"• {keyword.title()}",
                     fill=colors["fg"], font=ImageFont.load_default(16), anchor="mm")
            keyword_y += 30

        meaning = card.meaning[:100] + "..." if len(card.meaning) > 100 else card.meaning
        draw.multiline_text((width // 2, 350), meaning, fill=(255, 255, 200),
                           font=ImageFont.load_default(14), anchor="mm", align="center")

        number_text = f"#{card.number:02d}" if card.number is not None else "XX"
        draw.text((width - 40, height - 40), number_text, fill=colors["accent"],
                 font=ImageFont.load_default(20))

        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG", quality=85)
        img_bytes.seek(0)
        return img_bytes

    @classmethod
    def _generate_simple_image(cls, card: TarotCard, size: Tuple[int, int]) -> io.BytesIO:
        width, height = size
        img = Image.new("RGB", (width, height), (0, 0, 50))
        draw = ImageDraw.Draw(img)
        draw.text((width // 2, height // 2), card.name, fill=(255, 255, 255),
                 font=ImageFont.load_default(20), anchor="mm")
        orient_text = "R" if card.is_reversed else "U"
        draw.text((width // 2, height // 2 + 30), orient_text,
                 fill=(255, 200, 100), font=ImageFont.load_default(16), anchor="mm")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes.seek(0)
        return img_bytes