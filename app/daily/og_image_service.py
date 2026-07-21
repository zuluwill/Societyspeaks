"""Render daily question share cards as PNG for OG/Twitter unfurls."""

from __future__ import annotations

from typing import Dict, Optional

from app.lib import og_card_render as ocr


def is_available() -> bool:
    return ocr.is_available()


def render_daily_question_png(
    *,
    question_number: int,
    question_text: str,
    stats: Optional[Dict[str, int]] = None,
    badge_label: str = 'Daily Civic Question',
    agree_label: str = 'Agree',
    disagree_label: str = 'Disagree',
    unsure_label: str = 'Unsure',
    responses_label: Optional[str] = None,
) -> Optional[bytes]:
    """Render a 1200×630 share card. Returns PNG bytes or None if Pillow missing."""
    if stats and stats.get('total', 0) > 0:
        footer_left = responses_label or f"{stats.get('total', 0)} responses"
    else:
        footer_left = 'Vote in under 2 minutes'

    stats_snapshot = stats

    def draw_stats(draw, x, bar_y):
        if not stats_snapshot or stats_snapshot.get('total', 0) <= 0:
            return
        label_font = ocr.load_font(ocr.BODY_FONT_CANDIDATES, 24)
        value_font = ocr.load_font(ocr.BODY_FONT_CANDIDATES, 24)
        content_width = ocr.CARD_SIZE[0] - (ocr.PADDING * 2)
        x_label = x
        x_bar = x + 130
        bar_width = content_width - 230
        bar_height = 24
        x_value = x + content_width - 70
        ocr.draw_bar(
            draw,
            y=bar_y,
            label=agree_label,
            pct=int(stats_snapshot.get('agree', 0)),
            color=ocr.AGREE,
            label_font=label_font,
            value_font=value_font,
            x_label=x_label,
            x_bar=x_bar,
            bar_width=bar_width,
            bar_height=bar_height,
            x_value=x_value,
        )
        ocr.draw_bar(
            draw,
            y=bar_y + 44,
            label=disagree_label,
            pct=int(stats_snapshot.get('disagree', 0)),
            color=ocr.DISAGREE,
            label_font=label_font,
            value_font=value_font,
            x_label=x_label,
            x_bar=x_bar,
            bar_width=bar_width,
            bar_height=bar_height,
            x_value=x_value,
        )
        ocr.draw_bar(
            draw,
            y=bar_y + 88,
            label=unsure_label,
            pct=int(stats_snapshot.get('unsure', 0)),
            color=ocr.UNSURE,
            label_font=label_font,
            value_font=value_font,
            x_label=x_label,
            x_bar=x_bar,
            bar_width=bar_width,
            bar_height=bar_height,
            x_value=x_value,
        )

    return ocr.render_branded_card(
        badge_text=f'{badge_label} #{question_number}',
        headline=question_text,
        footer_left=footer_left,
        headline_max_lines=3,
        body_height=112,
        body_draw=draw_stats,
    )
