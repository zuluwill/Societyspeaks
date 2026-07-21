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
PADDING = 72

# Palette — light, crisp, on-brand.
BG_TOP = (255, 255, 255)
BG_BOTTOM = (233, 241, 254)
INK = (15, 23, 42)          # headline / primary text
MUTED = (100, 116, 139)     # footer / secondary
ACCENT = (37, 99, 235)      # brand blue
DIVIDER = (219, 229, 245)
BADGE_TEXT = (255, 255, 255)

# Vote-bar colours (daily card).
TEXT = INK
BAR_TRACK = (223, 231, 244)
AGREE = ACCENT
DISAGREE = (220, 38, 38)
UNSURE = (100, 116, 139)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FONTS_ROOT = _REPO_ROOT / 'app' / 'static' / 'fonts'
_LOGO_PATH = _REPO_ROOT / 'app' / 'static' / 'logos' / 'society_speaks_logo_blue_fixed.png'

# Bundled variable fonts first (Fraunces / Inter, OFL); OS/PIL fallbacks after.
DISPLAY_FONT_CANDIDATES = [
    _FONTS_ROOT / 'Fraunces.ttf',
    _FONTS_ROOT / 'Fraunces-Bold.ttf',
    Path('/Library/Fonts/Georgia.ttf'),
    Path('/System/Library/Fonts/Supplemental/Georgia.ttf'),
    Path('/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf'),
]

BODY_FONT_CANDIDATES = [
    _FONTS_ROOT / 'Inter.ttf',
    _FONTS_ROOT / 'Inter-Medium.ttf',
    Path('/System/Library/Fonts/HelveticaNeue.ttc'),
    Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
]


def is_available() -> bool:
    return PIL_AVAILABLE


def load_font(candidates: List[Path], size: int, variation: Optional[str] = None):
    """Load the first available font; for variable fonts, apply a named weight."""
    for path in candidates:
        try:
            if path.is_file():
                font = ImageFont.truetype(str(path), size=size)
                if variation:
                    try:
                        font.set_variation_by_name(variation)
                    except Exception:  # noqa: BLE001 — static fallback fonts have no named instances
                        pass
                return font
        except (OSError, ValueError):
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover — very old Pillow
        return ImageFont.load_default()


def paint_gradient(img: "Image.Image") -> None:
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


def _fit_headline(draw, text: str, candidates, max_width: int, max_lines: int, sizes):
    """Pick the largest headline size whose wrapped lines all fit the width."""
    for size in sizes:
        font = load_font(candidates, size, variation='Bold')
        lines = wrap_lines(draw, text, font, max_width, max_lines)
        if len(lines) <= max_lines and all(
            draw.textlength(ln, font=font) <= max_width for ln in lines
        ):
            return font, lines, int(size * 1.18)
    smallest = sizes[-1]
    font = load_font(candidates, smallest, variation='Bold')
    return font, wrap_lines(draw, text, font, max_width, max_lines), int(smallest * 1.18)


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


def _paste_logo(img, right_x: int, top_y: int, target_h: int = 40) -> None:
    """Paste the brand logo, scaled to target_h, with its right edge at right_x."""
    try:
        if not _LOGO_PATH.is_file():
            return
        logo = Image.open(_LOGO_PATH).convert('RGBA')
        scale = target_h / logo.height
        w = int(logo.width * scale)
        logo = logo.resize((w, target_h), Image.LANCZOS)
        img.paste(logo, (right_x - w, top_y), logo)
    except Exception:  # noqa: BLE001 — logo is decorative; never fail the card
        logger.debug('OG logo paste failed', exc_info=True)


def render_branded_card(
    *,
    badge_text: str,
    headline: str,
    footer_left: str,
    footer_right: str = 'societyspeaks.io',
    headline_max_lines: int = 4,
    body_height: int = 0,
    body_draw: Optional[Callable[["ImageDraw.ImageDraw", int, int], None]] = None,
) -> Optional[bytes]:
    """Render a standard Society Speaks OG card. Returns PNG bytes or None."""
    if not PIL_AVAILABLE:
        return None

    img = Image.new('RGB', CARD_SIZE, BG_TOP)
    paint_gradient(img)
    draw = ImageDraw.Draw(img, 'RGBA')

    width, height = CARD_SIZE
    content_width = width - (PADDING * 2)
    x = PADDING

    # --- Top row: badge pill (left) + logo (right) ---
    badge_font = load_font(BODY_FONT_CANDIDATES, 24, variation='SemiBold')
    badge_h = 48
    badge_top = PADDING - 6
    pad_x = 20
    badge_w = draw.textlength(badge_text, font=badge_font) + pad_x * 2
    draw.rounded_rectangle(
        (x, badge_top, x + badge_w, badge_top + badge_h),
        radius=badge_h // 2,
        fill=ACCENT,
    )
    _, t, _, b = draw.textbbox((0, 0), badge_text, font=badge_font)
    draw.text((x + pad_x, badge_top + (badge_h - (b - t)) // 2 - t), badge_text,
              fill=BADGE_TEXT, font=badge_font)
    _paste_logo(img, right_x=width - PADDING, top_y=badge_top + 6, target_h=38)

    # --- Middle zone: headline (+ optional body), vertically centred as a group ---
    # A card with body content (e.g. vote bars) uses a smaller headline so the
    # group still fits; a headline-only card can go large and dramatic.
    headline_sizes = (50, 46, 42, 38) if body_draw else (66, 60, 54, 48, 42)
    headline_font, lines, line_h = _fit_headline(
        draw, (headline or '').strip(), DISPLAY_FONT_CANDIDATES,
        content_width, headline_max_lines, headline_sizes,
    )
    headline_block_h = len(lines) * line_h

    footer_text_y = height - PADDING - 20
    divider_y = footer_text_y - 30
    middle_top = badge_top + badge_h + 44
    middle_bottom = divider_y - 30
    middle_h = middle_bottom - middle_top

    group_h = headline_block_h + ((28 + body_height) if body_draw else 0)
    start_y = middle_top + max(0, (middle_h - group_h) // 2)

    y = start_y
    for line in lines:
        draw.text((x, y), line, fill=INK, font=headline_font)
        y += line_h

    if body_draw is not None:
        body_draw(draw, x, start_y + headline_block_h + 28)

    # --- Footer: hairline divider + meta row ---
    draw.line([(x, divider_y), (x + content_width, divider_y)], fill=DIVIDER, width=2)
    footer_font = load_font(BODY_FONT_CANDIDATES, 24, variation='Medium')
    url_font = load_font(BODY_FONT_CANDIDATES, 24, variation='SemiBold')
    draw.text((x, footer_text_y), footer_left, fill=MUTED, font=footer_font)
    url_w = draw.textlength(footer_right, font=url_font)
    draw.text((x + content_width - url_w, footer_text_y), footer_right, fill=ACCENT, font=url_font)

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()
