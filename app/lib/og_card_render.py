"""Shared 1200×630 OG card rendering for social unfurls (Bluesky, X, iMessage, etc.)."""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    PIL_AVAILABLE = False

CARD_SIZE: Tuple[int, int] = (1200, 630)
PADDING = 56
BG_TOP = (239, 246, 255)
BG_BOTTOM = (191, 219, 254)
TEXT = (31, 41, 55)
MUTED = (107, 114, 128)
ACCENT = (37, 99, 235)
BAR_TRACK = (229, 231, 235)
AGREE = ACCENT
DISAGREE = (220, 38, 38)
UNSURE = (107, 114, 128)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FONTS_ROOT = _REPO_ROOT / 'app' / 'static' / 'fonts'

DISPLAY_FONT_CANDIDATES = [
    _FONTS_ROOT / 'Fraunces-Bold.ttf',
    _FONTS_ROOT / 'Fraunces.ttf',
    Path('/Library/Fonts/Georgia.ttf'),
    Path('/System/Library/Fonts/Supplemental/Georgia.ttf'),
    Path('/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf'),
]

BODY_FONT_CANDIDATES = [
    _FONTS_ROOT / 'Inter-Medium.ttf',
    _FONTS_ROOT / 'Inter.ttf',
    Path('/System/Library/Fonts/HelveticaNeue.ttc'),
    Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
]


def is_available() -> bool:
    return PIL_AVAILABLE


def load_font(candidates: List[Path], size: int):
    for path in candidates:
        try:
            if path.is_file():
                return ImageFont.truetype(str(path), size=size)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


def paint_gradient(img: Image.Image) -> None:
    draw = ImageDraw.Draw(img)
    width, height = img.size
    for y in range(height):
        ratio = y / max(height - 1, 1)
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * ratio)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * ratio)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))


def wrap_lines(draw, text: str, font, max_width: int, max_lines: int) -> List[str]:
    words = (text or '').split()
    lines: List[str] = []
    current: List[str] = []
    truncated = False
    for word in words:
        candidate = ' '.join(current + [word])
        if draw.textlength(candidate, font=font) <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(' '.join(current))
            current = [word]
            if len(lines) >= max_lines:
                truncated = True
                current = []
                break
    if current and len(lines) < max_lines:
        lines.append(' '.join(current))
    elif current:
        truncated = True
    if truncated and lines:
        last = lines[-1]
        while draw.textlength(last + '…', font=font) > max_width and ' ' in last:
            last = last.rsplit(' ', 1)[0]
        lines[-1] = last + '…'
    return lines


def draw_bar(
    draw,
    *,
    y: int,
    label: str,
    pct: int,
    color,
    label_font,
    value_font,
    x_label: int,
    x_bar: int,
    bar_width: int,
    bar_height: int,
    x_value: int,
) -> None:
    draw.text((x_label, y), label, fill=TEXT, font=label_font)
    draw.rounded_rectangle(
        (x_bar, y + 2, x_bar + bar_width, y + 2 + bar_height),
        radius=bar_height // 2,
        fill=BAR_TRACK,
    )
    fill_width = max(int(bar_width * max(pct, 0) / 100), 0)
    if fill_width > 0:
        draw.rounded_rectangle(
            (x_bar, y + 2, x_bar + fill_width, y + 2 + bar_height),
            radius=bar_height // 2,
            fill=color,
        )
    draw.text((x_value, y), f'{pct}%', fill=TEXT, font=value_font)


def render_branded_card(
    *,
    badge_text: str,
    headline: str,
    footer_left: str,
    footer_right: str = 'societyspeaks.io',
    headline_max_lines: int = 4,
    body_draw: Optional[Callable[[ImageDraw.ImageDraw, int, int], None]] = None,
) -> Optional[bytes]:
    """Render a standard Society Speaks OG card. Returns PNG bytes or None."""
    if not PIL_AVAILABLE:
        return None

    img = Image.new('RGB', CARD_SIZE, BG_TOP)
    paint_gradient(img)
    draw = ImageDraw.Draw(img, 'RGBA')

    badge_font = load_font(BODY_FONT_CANDIDATES, 22)
    headline_font = load_font(DISPLAY_FONT_CANDIDATES, 42)
    footer_font = load_font(BODY_FONT_CANDIDATES, 22)

    content_width = CARD_SIZE[0] - (PADDING * 2)
    x = PADDING

    badge_w = draw.textlength(badge_text, font=badge_font) + 32
    draw.rounded_rectangle(
        (x, PADDING, x + badge_w, PADDING + 40),
        radius=20,
        fill=ACCENT,
    )
    draw.text((x + 16, PADDING + 8), badge_text, fill=(255, 255, 255), font=badge_font)

    question_y = PADDING + 64
    lines = wrap_lines(draw, (headline or '').strip(), headline_font, content_width, headline_max_lines)
    for line in lines:
        draw.text((x, question_y), line, fill=TEXT, font=headline_font)
        question_y += 52

    if body_draw is not None:
        body_draw(draw, x, question_y + 16)

    footer_y = CARD_SIZE[1] - PADDING - 24
    draw.text((x, footer_y), footer_left, fill=MUTED, font=footer_font)
    draw.text((x + content_width - 180, footer_y), footer_right, fill=ACCENT, font=footer_font)

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()
