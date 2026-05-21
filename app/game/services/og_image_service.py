"""Render the Society Play outcome share card as a PNG.

Plan §8.3: designed share card, 1200×630, Wrapped-style identity artifact.
Brands the artifact with the Society Speaks logo + wordmark + URL footer so
share previews on Twitter, iMessage, Slack and LinkedIn unfurl with full visual
identity rather than the plain text/og:title fallback the SVG endpoint gives
on those platforms.

Graceful degradation:
- If Pillow can't import on the host, callers fall back to the SVG endpoint.
- If the preferred font files aren't on disk, a fallback chain finds the best
  available serif/sans on the system; the route still works, the typography
  just degrades.
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    PIL_AVAILABLE = True
except ImportError:  # pragma: no cover — exercised only in environments without Pillow
    PIL_AVAILABLE = False


_CARD_SIZE = (1200, 630)
_PADDING = 64
_DARK_BG = (12, 15, 20)
_SURFACE = (21, 26, 34)
_BORDER = (42, 52, 68)
_TEXT = (240, 244, 248)
_MUTED = (148, 163, 184)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_STATIC_ROOT = _REPO_ROOT / 'app' / 'static'
_FONTS_ROOT = _STATIC_ROOT / 'fonts'
_LOGO_PATH = _STATIC_ROOT / 'logos' / 'society_speaks_logo_white_fixed.png'

# Preferred (ship in app/static/fonts/) → system fallbacks → PIL default.
_DISPLAY_FONT_CANDIDATES = [
    _FONTS_ROOT / 'Fraunces-Bold.ttf',
    _FONTS_ROOT / 'Fraunces.ttf',
    Path('/Library/Fonts/Georgia.ttf'),
    Path('/System/Library/Fonts/Supplemental/Georgia.ttf'),
    Path('/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf'),
    Path('/usr/share/fonts/dejavu/DejaVuSerif-Bold.ttf'),
]

_BODY_FONT_CANDIDATES = [
    _FONTS_ROOT / 'Inter-Medium.ttf',
    _FONTS_ROOT / 'Inter.ttf',
    Path('/System/Library/Fonts/HelveticaNeue.ttc'),
    Path('/System/Library/Fonts/Helvetica.ttc'),
    Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
    Path('/usr/share/fonts/dejavu/DejaVuSans.ttf'),
]


def is_available() -> bool:
    """True when the host can actually render PNGs."""
    return PIL_AVAILABLE


def _load_font(candidates: List[Path], size: int):
    """Return the first available TrueType from candidates, or PIL default."""
    for path in candidates:
        try:
            if path.is_file():
                return ImageFont.truetype(str(path), size=size)
        except (OSError, ValueError):
            continue
    logger.warning('OG render: no preferred font found, using PIL default at size %d', size)
    return ImageFont.load_default()


def _hex_to_rgb(value: str) -> Tuple[int, int, int]:
    """Convert '#d4a853' or 'hsl(...)' to RGB. HSL strings fall back to gold."""
    if not value:
        return (212, 168, 83)
    s = value.strip().lower()
    if s.startswith('hsl'):
        return _hsl_string_to_rgb(s)
    s = s.lstrip('#')
    if len(s) == 6:
        try:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        except ValueError:
            pass
    return (212, 168, 83)


def _hsl_string_to_rgb(value: str) -> Tuple[int, int, int]:
    """Parse 'hsl(120, 55%, 58%)' into RGB."""
    inside = value[value.find('(') + 1:value.rfind(')')]
    parts = [p.strip().rstrip('%') for p in inside.split(',')]
    try:
        h, s, l = float(parts[0]) / 360.0, float(parts[1]) / 100.0, float(parts[2]) / 100.0
    except (IndexError, ValueError):
        return (212, 168, 83)
    import colorsys
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return (int(r * 255), int(g * 255), int(b * 255))


def _wrap_lines(draw, text: str, font, max_width: int, max_lines: int) -> List[str]:
    """Greedy word-wrap. Truncates with ellipsis when text overflows max_lines."""
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
                current = []  # don't append the just-broken word
                break
    if current and len(lines) < max_lines:
        lines.append(' '.join(current))
    elif current and len(lines) >= max_lines:
        truncated = True
    if truncated and lines:
        last = lines[-1]
        while draw.textlength(last + '…', font=font) > max_width and ' ' in last:
            last = last.rsplit(' ', 1)[0]
        lines[-1] = last + '…'
    return lines


def render_outcome_png(*, run, view: Dict[str, Any], emblem: Dict[str, Any]) -> Optional[bytes]:
    """Render the outcome share card. Returns PNG bytes or None if Pillow missing."""
    if not PIL_AVAILABLE:
        return None

    accent = _hex_to_rgb(emblem.get('accent', '#d4a853'))
    headline = (view.get('headline') or '').strip() or 'Your society lives on.'
    governance = (view.get('governance_label') or '').strip()
    society_name = (getattr(run, 'society_name', None) or 'Your society').strip()
    scenario_title = (view.get('scenario', {}).get('title') or '').strip()
    trait_chips = (view.get('trait_chips') or [])[:3]

    axis = view.get('axis') or {}
    ta = float(axis.get('trust_autonomy', 50))
    pf = float(axis.get('prosperity_fairness', 50))

    img = Image.new('RGB', _CARD_SIZE, _DARK_BG)
    _paint_background_glow(img, accent)
    draw = ImageDraw.Draw(img, 'RGBA')

    display_xl = _load_font(_DISPLAY_FONT_CANDIDATES, 58)
    body_md = _load_font(_BODY_FONT_CANDIDATES, 24)
    body_sm = _load_font(_BODY_FONT_CANDIDATES, 20)
    body_xs = _load_font(_BODY_FONT_CANDIDATES, 18)
    wordmark = _load_font(_DISPLAY_FONT_CANDIDATES, 30)

    _paint_brand_header(img, draw, wordmark, body_xs)
    _paint_axis_plot(draw, ta, pf, accent)

    # Headline block — left column, sized to clear the axis plot on the right.
    headline_x = _PADDING
    headline_y = 168
    headline_width = 700
    lines = _wrap_lines(draw, headline, display_xl, headline_width, max_lines=4)
    line_height = 70
    for i, line in enumerate(lines):
        draw.text((headline_x, headline_y + i * line_height), line, font=display_xl, fill=_TEXT)
    headline_bottom = headline_y + len(lines) * line_height

    meta_y = headline_bottom + 16
    if governance:
        draw.text((headline_x, meta_y), governance, font=body_md, fill=accent)
        meta_y += 36
    if society_name:
        draw.text((headline_x, meta_y), society_name, font=body_sm, fill=_MUTED)
        meta_y += 28
    if scenario_title:
        draw.text((headline_x, meta_y), scenario_title, font=body_xs, fill=_MUTED)
        meta_y += 26

    if trait_chips:
        _paint_trait_chips(draw, trait_chips, headline_x, meta_y + 12, body_xs, accent)

    _paint_footer(img, draw, body_xs, accent)

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def _paint_background_glow(img: 'Image.Image', accent: Tuple[int, int, int]) -> None:
    """Soft radial glow keyed to the player's emblem colour, top-right."""
    glow = Image.new('RGBA', _CARD_SIZE, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    cx, cy = 980, 80
    for radius, alpha in [(560, 22), (440, 32), (320, 42), (200, 56), (110, 72)]:
        gdraw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill=(accent[0], accent[1], accent[2], alpha),
        )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=40))
    img.paste(glow, (0, 0), glow)


def _paint_brand_header(img: 'Image.Image', draw, wordmark_font, sub_font) -> None:
    """Top-left: SS logo + 'Tradeoffs' wordmark + subtitle."""
    try:
        if _LOGO_PATH.is_file():
            logo = Image.open(_LOGO_PATH).convert('RGBA')
            logo_h = 56
            scale = logo_h / logo.height
            logo_w = max(1, int(logo.width * scale))
            logo = logo.resize((logo_w, logo_h), Image.Resampling.LANCZOS)
            img.paste(logo, (_PADDING, _PADDING), logo)
            text_x = _PADDING + logo_w + 20
        else:
            text_x = _PADDING
    except Exception:  # noqa: BLE001 — never let logo failure block the render
        logger.warning('OG render: logo load failed, continuing without it', exc_info=True)
        text_x = _PADDING

    draw.text((text_x, _PADDING - 4), 'Tradeoffs', font=wordmark_font, fill=_TEXT)
    draw.text(
        (text_x, _PADDING + 36),
        'a Society Speaks game',
        font=sub_font,
        fill=_MUTED,
    )


def _paint_axis_plot(draw, ta: float, pf: float, accent: Tuple[int, int, int]) -> None:
    """Right-column identity plot — Trust↔Autonomy × Prosperity↔Fairness."""
    plot_size = 340
    plot_x = _CARD_SIZE[0] - _PADDING - plot_size
    plot_y = 168
    plot_right = plot_x + plot_size
    plot_bottom = plot_y + plot_size

    draw.rounded_rectangle(
        (plot_x, plot_y, plot_right, plot_bottom),
        radius=20,
        fill=_SURFACE,
        outline=_BORDER,
        width=2,
    )
    # Quartile grid (faint).
    for i in range(1, 4):
        offset = int(plot_size * i / 4)
        draw.line(
            ((plot_x + offset, plot_y), (plot_x + offset, plot_bottom)),
            fill=(148, 163, 184, 24),
            width=1,
        )
        draw.line(
            ((plot_x, plot_y + offset), (plot_right, plot_y + offset)),
            fill=(148, 163, 184, 24),
            width=1,
        )
    # Crosshairs.
    mid_x = plot_x + plot_size // 2
    mid_y = plot_y + plot_size // 2
    draw.line(((plot_x, mid_y), (plot_right, mid_y)), fill=(148, 163, 184, 60), width=1)
    draw.line(((mid_x, plot_y), (mid_x, plot_bottom)), fill=(148, 163, 184, 60), width=1)

    # Axis labels (clipped tight to plot edges so they read at small thumb sizes).
    label_font = _load_font(_BODY_FONT_CANDIDATES, 16)
    label_color = _MUTED
    draw.text((mid_x, plot_y - 24), 'PROSPERITY', font=label_font, fill=label_color, anchor='mm')
    draw.text((mid_x, plot_bottom + 22), 'FAIRNESS', font=label_font, fill=label_color, anchor='mm')
    draw.text((plot_x - 12, mid_y), 'TRUST', font=label_font, fill=label_color, anchor='rm')
    draw.text((plot_right + 12, mid_y), 'AUTONOMY', font=label_font, fill=label_color, anchor='lm')

    # Player dot — clamped inside the plot box.
    dot_x = plot_x + int(plot_size * max(0.0, min(100.0, ta)) / 100)
    dot_y = plot_y + int(plot_size * max(0.0, min(100.0, pf)) / 100)
    dot_radius = 13
    halo_alpha = (accent[0], accent[1], accent[2], 80)
    draw.ellipse(
        (dot_x - 32, dot_y - 32, dot_x + 32, dot_y + 32),
        fill=halo_alpha,
    )
    draw.ellipse(
        (dot_x - dot_radius, dot_y - dot_radius, dot_x + dot_radius, dot_y + dot_radius),
        fill=accent,
        outline=_DARK_BG,
        width=3,
    )


def _paint_trait_chips(draw, chips: List[str], x: int, y: int, font, accent: Tuple[int, int, int]) -> None:
    """Pill-style chips so the identity reads at a glance."""
    pad_x = 14
    pad_y = 7
    spacing = 10
    cursor = x
    for chip in chips:
        text_w = int(draw.textlength(chip, font=font))
        chip_w = text_w + pad_x * 2
        chip_h = 32
        draw.rounded_rectangle(
            (cursor, y, cursor + chip_w, y + chip_h),
            radius=16,
            fill=_SURFACE,
            outline=_BORDER,
            width=1,
        )
        draw.text((cursor + pad_x, y + pad_y - 2), chip, font=font, fill=_MUTED)
        cursor += chip_w + spacing


def _paint_footer(img: 'Image.Image', draw, font, accent: Tuple[int, int, int]) -> None:
    """Footer: domain + tagline, with a 1px accent line above."""
    footer_y = _CARD_SIZE[1] - 70
    draw.line(
        ((_PADDING, footer_y - 18), (_CARD_SIZE[0] - _PADDING, footer_y - 18)),
        fill=_BORDER,
        width=1,
    )
    draw.text(
        (_PADDING, footer_y),
        'societyspeaks.io/play',
        font=font,
        fill=accent,
    )
    tagline = 'Every choice costs something.'
    tagline_w = int(draw.textlength(tagline, font=font))
    draw.text(
        (_CARD_SIZE[0] - _PADDING - tagline_w, footer_y),
        tagline,
        font=font,
        fill=_MUTED,
    )
