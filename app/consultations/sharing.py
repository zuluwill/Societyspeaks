"""Ready-to-send links for a consultation, and the preview chat apps fetch.

The participant page stays private. A chat app that expands a pasted link is
shown the question and who is asking, never the statements or the votes.
"""
from urllib.parse import quote
from typing import Optional

from flask_babel import gettext as _

# User agents that fetch a URL only to build a link preview. Matched as
# substrings, lowercased. A normal browser must not match.
_LINK_PREVIEW_AGENTS = (
    'slackbot',
    'twitterbot',
    'facebookexternalhit',
    'facebot',
    'linkedinbot',
    'telegrambot',
    'whatsapp',
    'discordbot',
    'skypeuripreview',
    'microsoftpreview',
    'teams/',
    'applebot',
    'redditbot',
    'embedly',
    'iframely',
    'quora link preview',
    'vkshare',
    'pinterestbot',
    'bluesky',
    'bsky',
)


def is_link_preview(user_agent: Optional[str]) -> bool:
    agent = (user_agent or '').lower()
    return any(name in agent for name in _LINK_PREVIEW_AGENTS)


def short_message(consultation) -> str:
    """One message for a chat. The link is added by the destination."""
    return _(
        '%(organisation)s is asking: “%(question)s”. '
        'Two minutes on your phone. No login, and your answers are anonymous.',
        organisation=consultation.organisation_name,
        question=consultation.question,
    )


def _fit(text: str, limit: int) -> str:
    text = ' '.join((text or '').split())
    if len(text) <= limit:
        return text
    if limit < 2:
        return text[:limit]
    trimmed = text[:limit - 1].rstrip()
    return trimmed + '…'


def _q(value: str) -> str:
    return quote(value or '', safe='')


def share_groups(consultation, url: str) -> list:
    """Destinations for the share page.

    Each item is either a link (``href``) or text to copy (``text``).
    TikTok and Instagram have no way to open an arbitrary link from a post,
    so those two copy a caption instead.
    """
    message = short_message(consultation)
    with_link = f'{message}\n\n{url}'
    x_text = _fit(message, 240)
    bluesky_text = _fit(f'{message} {url}', 300)
    teams_text = _fit(message, 400)
    subject = _fit(f'{consultation.organisation_name}: {consultation.question}', 120)

    def link(item_id, label, href):
        return {'id': item_id, 'label': label, 'href': href, 'text': None}

    def copy(item_id, label, text):
        return {'id': item_id, 'label': label, 'href': None, 'text': text}

    return [
        {
            'title': _('Send the link'),
            'hint': _('The question shows as a preview when the link is pasted.'),
            'items': [
                link('whatsapp', 'WhatsApp', f'https://wa.me/?text={_q(with_link)}'),
                link('teams', 'Teams', f'https://teams.microsoft.com/share?href={_q(url)}&msgText={_q(teams_text)}'),
                copy('slack', _('Copy for Slack'), with_link),
                link('telegram', 'Telegram', f'https://t.me/share/url?url={_q(url)}&text={_q(message)}'),
                link('email', _('Email'), f'mailto:?subject={_q(subject)}&body={_q(with_link)}'),
            ],
        },
        {
            'title': _('Post it'),
            'hint': None,
            'items': [
                link('x', 'X', f'https://x.com/intent/tweet?text={_q(x_text)}&url={_q(url)}'),
                link('facebook', 'Facebook', f'https://www.facebook.com/sharer/sharer.php?u={_q(url)}'),
                link('threads', 'Threads', f'https://www.threads.net/intent/post?text={_q(bluesky_text)}'),
                link('bluesky', 'Bluesky', f'https://bsky.app/intent/compose?text={_q(bluesky_text)}'),
                link('linkedin', 'LinkedIn', f'https://www.linkedin.com/sharing/share-offsite/?url={_q(url)}'),
            ],
        },
        {
            'title': _('A caption to paste'),
            'hint': _('On TikTok and Instagram, put the QR code on screen or the link in your bio.'),
            'items': [
                copy('tiktok', _('Copy for TikTok'), with_link),
                copy('instagram', _('Copy for Instagram'), with_link),
            ],
        },
    ]


def render_share_card(consultation) -> Optional[bytes]:
    """A 1200×630 preview of the question. None when the renderer is unavailable."""
    from app.lib.og_card_render import render_branded_card

    organisation = ' '.join((consultation.organisation_name or '').split())
    badge = organisation if len(organisation) <= 42 else organisation[:41].rstrip() + '…'
    return render_branded_card(
        badge_text=badge or 'Society Speaks',
        headline=consultation.question,
        footer_left=_('Two minutes · No login · Anonymous'),
        headline_max_lines=4,
    )
