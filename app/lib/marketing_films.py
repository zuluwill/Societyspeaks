"""Product films on the marketing pages.

The films are made in the video studio (``societyspeaks-video-studio``) from the
real product on synthetic data. Its ``production/web-export.mjs`` writes the web
renditions with content-hashed names and a manifest; ``scripts/publish_marketing_films.py``
uploads the files to object storage under ``marketing_films/`` and copies the
manifest to ``app/lib/marketing_films.json``.

Pages ask for a film with the ``marketing_film(slug)`` Jinja global, which
returns ``None`` while ``MARKETING_FILMS_ENABLED`` is off or the film is not in
the manifest, so every page keeps a working layout without it.

Files are served by ``/media/films/<name>`` (byte ranges, for Safari and for
seeking) unless ``MARKETING_FILMS_BASE_URL`` points at a CDN or public bucket.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from flask import Response, abort, current_app, request, send_file, url_for
from flask_babel import lazy_gettext as _l
from werkzeug.http import parse_range_header

from app.lib.cdn_cache import strip_cookie_from_vary

MANIFEST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'marketing_films.json')
STORAGE_PREFIX = 'marketing_films/'
# Names carry a content hash, so a URL never changes meaning and can be cached for a year.
FILM_CACHE_CONTROL = 'public, max-age=31536000, immutable'
_FILE_NAME = re.compile(r'^[a-z0-9-]+(?:\.en-GB)?\.[0-9a-f]{10}\.(?:mp4|jpg|webp|vtt)$')
_MIME = {'.mp4': 'video/mp4', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.vtt': 'text/vtt'}
_CHUNK = 256 * 1024

# Published on 3 October 2026 (Europe/London). Used for VideoObject structured data.
_UPLOAD_DATE = '2026-10-03T09:00:00+01:00'

# Title and description are translated; the films themselves are in English, so the
# text alternative of a silent film (``shows``) is its English on-screen words.
FILMS: dict[str, dict] = {
    'home': {
        'title': _l('Society Speaks in one minute'),
        'description': _l('How Society Speaks turns quick votes on short statements into a map of where people agree, which ideas win support in every group, and where the real divisions lie.'),
    },
    'narrated': {
        'title': _l('Everything Society Speaks does'),
        'description': _l('A tour of Society Speaks: the daily question, the free Daily Brief, Personal Briefs, voting under news articles, consultations for councils and organisations, and the Tradeoffs game.'),
    },
    'consultation': {
        'title': _l('Run your own consultation'),
        'description': _l('Ask one question, share a link or a QR code, and get a report on where your audience agrees, disagrees, is unsure or is split.'),
        'shows': [
            'Ask one question.', 'We draft the statements.', 'You edit and approve them.',
            'Put the code on the big screen.', 'Two minutes on a phone. No login. Anonymous.',
            'Then show the room where it stands.', 'And read the report.',
            'Where they agree. Where they disagree. Where they are unsure. And where they are split.',
            'Free for 14 days. No card.', 'See where your audience agrees, disagrees or is unsure.',
        ],
    },
    'consultation-report': {
        'title': _l('The consultation report'),
        'description': _l('What you get back from a consultation: the headline, the themes, every statement at a glance, what to ask next, and what the results do not show.'),
        'shows': [
            'A poll gives you a number. This gives you the picture.', 'The headline, in plain words.',
            'The themes behind it.', 'Every statement, at a glance.',
            'Where they agree. Where they disagree. Where they are unsure. And where they are split.',
            'What to ask next.', 'And what the results do not show.', 'Every figure, ready to export.',
            'A report you can forward.',
        ],
    },
    'consultation-participant': {
        'title': _l('What taking part looks like'),
        'description': _l('What your audience sees: scan the code, answer one statement at a time, done. No login, and anonymous.'),
        'shows': [
            'Point your phone at the code.', 'One statement at a time.', 'Agree, disagree or unsure.',
            'No login. Anonymous.', 'Answer one yourself in two minutes.',
        ],
    },
    'councils': {
        'title': _l('Consultations for councils and public bodies'),
        'description': _l('Put a whole plan to residents, see the opinion groups behind the totals, and get a report you can put in front of members.'),
        'shows': [
            'Put the whole plan to the town.', 'Residents vote in seconds.', 'And add ideas of their own.',
            'See the groups, not just the totals.', 'Where the town agrees.', 'What bridges the divide.',
            'And where it splits.', 'A report you can put in front of members.',
            'Find out where your community agrees.',
        ],
    },
    'publishers': {
        'title': _l('Society Speaks for publishers'),
        'description': _l('Replace the comment section with structured voting under any article, styled to match your pages, with data your newsroom can report on.'),
        'shows': [
            'Replace the comment section.', 'Paste one iframe.', 'Styled to match your pages.',
            'See how your readers really divide.', 'What they agree on.', 'And what splits them.',
            'A signal your newsroom can use.', 'Data you can cite.',
            'Replace comment sections with structured public opinion.',
        ],
    },
    'brief': {
        'title': _l('The free Daily Brief'),
        'description': _l('The day’s news with how left, centre and right are framing it, then a question to answer and how everyone else voted.'),
        'shows': [
            'The news you need. Zero noise.', 'See how left, centre and right frame it.',
            'And who is covering it.', 'Then have your say.', 'And see how everyone else voted.',
            'In your inbox, at the time you choose.', 'The Daily Brief. Free, every day.',
        ],
    },
    'personal-briefs': {
        'title': _l('Personal Briefs'),
        'description': _l('One calm brief each morning, written from the sources and topics you choose.'),
        'shows': [
            'Not the news we pick. The news you follow.', 'Pick what you follow.',
            'One calm brief, every morning.', '£4.99 a month. 30 days free.',
            'One brief, from the sources you choose.',
        ],
    },
    'method': {
        'title': _l('How the analysis works'),
        'description': _l('From the vote matrix to opinion groups, margins of error and a test against chance, with the code open for anyone to check.'),
        'shows': [
            'Every vote is one cell.', 'People who vote alike end up together.', 'Two dimensions. Four groups.',
            'Every figure carries its margin of error.', 'Tested against chance, and re-run to check.',
            'Open source. Read the method.', 'Making disagreement useful again.',
        ],
    },
    'tradeoffs': {
        'title': _l('Tradeoffs, the daily game'),
        'description': _l('You govern for five turns, and every decision costs something. A new scenario every day.'),
        'shows': [
            'You’re in charge.', 'Every decision costs something.', 'Five turns. No easy answers.',
            'What kind of leader do you become?', 'Tradeoffs. A new scenario every day.',
        ],
    },
}


@lru_cache(maxsize=1)
def _manifest() -> dict:
    try:
        with open(MANIFEST_PATH, encoding='utf-8') as fh:
            return json.load(fh).get('films', {})
    except FileNotFoundError:
        return {}


def file_url(name: str, external: bool = False) -> str:
    base = current_app.config.get('MARKETING_FILMS_BASE_URL')
    if base:
        return f'{base}/{name}'
    return url_for('main.serve_film_file', filename=name, _external=external)


@dataclass(frozen=True)
class Film:
    slug: str
    title: str
    description: str
    duration: float
    narrated: bool
    files: dict
    transcript: list = field(default_factory=list)
    shows: list = field(default_factory=list)

    def url(self, key: str, external: bool = False) -> str:
        return file_url(self.files[key]['name'], external=external)

    def has(self, key: str) -> bool:
        return key in self.files

    @property
    def duration_label(self) -> str:
        total = int(round(self.duration))
        return f'{total // 60}:{total % 60:02d}'

    @property
    def iso_duration(self) -> str:
        total = int(round(self.duration))
        return f'PT{total // 60}M{total % 60}S'

    def json_ld(self) -> dict:
        """schema.org VideoObject, so search engines can show the film as a video result."""
        data = {
            '@context': 'https://schema.org',
            '@type': 'VideoObject',
            'name': str(self.title),
            'description': str(self.description),
            'thumbnailUrl': [self.url('poster_wide_jpg', external=True), self.url('poster_square_jpg', external=True)],
            'uploadDate': _UPLOAD_DATE,
            'duration': self.iso_duration,
            'contentUrl': self.url('wide_1080', external=True),
            'inLanguage': 'en-GB',
            'publisher': {'@type': 'Organization', 'name': 'Society Speaks', 'url': 'https://societyspeaks.io'},
        }
        if self.transcript:
            data['transcript'] = ' '.join(self.transcript)
        return data


def get_film(slug: str) -> Optional[Film]:
    """The film for ``slug``, or None when films are off or this one is not published."""
    if not current_app.config.get('MARKETING_FILMS_ENABLED'):
        return None
    meta, entry = FILMS.get(slug), _manifest().get(slug)
    if not meta or not entry:
        return None
    return Film(
        slug=slug,
        title=meta['title'],
        description=meta['description'],
        duration=float(entry['duration']),
        narrated=bool(entry.get('narrated')),
        files=entry['files'],
        transcript=list(entry.get('transcript') or []),
        shows=list(meta.get('shows') or []),
    )


# ---------------------------------------------------------------------------
# Serving: /media/films/<name>
# ---------------------------------------------------------------------------

def _local_dir() -> str:
    """Local development copy (git-ignored), filled by publish_marketing_films.py --local."""
    return os.path.join(current_app.root_path, 'static', 'films')


def serve_film_file(filename: str):
    if not _FILE_NAME.match(filename):
        abort(404)
    mimetype = _MIME[os.path.splitext(filename)[1]]
    local = os.path.join(_local_dir(), filename)
    if os.path.isfile(local):
        # Werkzeug answers Range and conditional requests for files on disk.
        response = send_file(local, mimetype=mimetype, conditional=True, etag=True, max_age=31536000)
        return _finish(response)

    from app.storage_utils import _get_s3_client, _s3_bucket, storage_provider
    if storage_provider() != 's3':
        abort(404)
    return _serve_from_s3(_get_s3_client(), _s3_bucket(), STORAGE_PREFIX + filename, mimetype)


def _finish(response):
    response.headers['Cache-Control'] = FILM_CACHE_CONTROL
    response.headers['Accept-Ranges'] = 'bytes'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    strip_cookie_from_vary(response)
    return response


def _s3_range(header: Optional[str]) -> Optional[str]:
    """One byte range from the request, in S3's syntax. Several ranges are answered whole."""
    parsed = parse_range_header(header) if header else None
    if not parsed or parsed.units != 'bytes' or len(parsed.ranges) != 1:
        return None
    start, stop = parsed.ranges[0]
    if start < 0:
        return f'bytes={start}'          # suffix: the last N bytes
    return f'bytes={start}-' if stop is None else f'bytes={start}-{stop - 1}'


def _serve_from_s3(client, bucket: str, key: str, mimetype: str):
    from botocore.exceptions import ClientError

    if request.method == 'HEAD':
        try:
            head = client.head_object(Bucket=bucket, Key=key)
        except ClientError as e:
            return _s3_error(e, key)
        response = Response(status=200, mimetype=mimetype)
        response.headers['Content-Length'] = str(head['ContentLength'])
        response.headers['ETag'] = head['ETag']
        return _finish(response)

    byte_range = _s3_range(request.headers.get('Range'))
    try:
        obj = client.get_object(Bucket=bucket, Key=key, **({'Range': byte_range} if byte_range else {}))
    except ClientError as e:
        if e.response.get('Error', {}).get('Code') == 'InvalidRange':
            size = client.head_object(Bucket=bucket, Key=key)['ContentLength']
            response = Response(status=416)
            response.headers['Content-Range'] = f'bytes */{size}'
            return _finish(response)
        return _s3_error(e, key)

    body = obj['Body']

    def stream():
        try:
            yield from body.iter_chunks(_CHUNK)
        finally:
            body.close()

    partial = bool(byte_range and obj.get('ContentRange'))
    response = Response(stream(), status=206 if partial else 200, mimetype=mimetype, direct_passthrough=True)
    response.headers['Content-Length'] = str(obj['ContentLength'])
    response.headers['ETag'] = obj['ETag']
    if partial:
        response.headers['Content-Range'] = obj['ContentRange']
    return _finish(response)


def _s3_error(error, key: str):
    code = error.response.get('Error', {}).get('Code')
    if code in ('NoSuchKey', '404', 'NotFound'):
        abort(404)
    current_app.logger.error('Film file %s unavailable: %s', key, error)
    return Response('Service unavailable', status=503)

