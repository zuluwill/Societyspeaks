"""Every hand-built ``{base_url}/path`` in app code must resolve to a real route.

Emails and background jobs often cannot call ``url_for(_external=True)`` (no
request context, no SERVER_NAME), so they concatenate a base URL and a path.
A path written by hand drifts silently when a route is renamed: the app serves
static files from the URL root, so a wrong path never fails to build and only
404s once a person clicks it.
"""
import re
from pathlib import Path

import pytest
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import RequestRedirect

_APP_DIR = Path(__file__).resolve().parents[1] / 'app'

# ``…base_url}/path`` or ``…get_base_url()}/path`` inside an f-string.
_HAND_BUILT_URL = re.compile(r'base_url(?:\(\))?\}(/[^"\'\s<>\\)]*)')
_STRIPE_PLACEHOLDER = re.compile(r'\{\{[^{}]*\}\}')
_FSTRING_FIELD = re.compile(r'\{[^{}]*\}?')


def _hand_built_paths():
    found = []
    for source in sorted(_APP_DIR.rglob('*.py')):
        for lineno, line in enumerate(source.read_text(encoding='utf-8').splitlines(), start=1):
            for match in _HAND_BUILT_URL.finditer(line):
                raw = match.group(1)
                if '(' in raw or '[' in raw or '$' in raw:
                    # A regular expression that parses URLs, not a link.
                    continue
                path = _STRIPE_PLACEHOLDER.sub('', raw).split('?', 1)[0].split('#', 1)[0]
                path = _FSTRING_FIELD.sub('1', path)
                where = f'{source.relative_to(_APP_DIR.parent)}:{lineno}'
                found.append(pytest.param(path, id=f'{where} {raw}'))
    return found


_PATHS = _hand_built_paths()


def test_scan_finds_hand_built_urls():
    assert len(_PATHS) > 20, 'scan regex no longer matches the codebase; update it'


@pytest.mark.parametrize('path', _PATHS)
def test_hand_built_url_resolves_to_a_route(app, path):
    adapter = app.url_map.bind('societyspeaks.io', url_scheme='https')
    try:
        endpoint, values = adapter.match(path, method='GET')
    except RequestRedirect:
        return
    except MethodNotAllowed:
        return
    except NotFound:
        pytest.fail(f'{path} matches no route')

    if endpoint == 'static':
        static_file = Path(app.static_folder) / values['filename']
        assert static_file.is_file(), (
            f'{path} matches no route: it falls through to the static-file '
            f'handler and {values["filename"]} is not a static file'
        )
