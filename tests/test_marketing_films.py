"""Product films on the marketing pages (app/lib/marketing_films.py, components/film.html)."""
import io
import json
import re
from unittest.mock import MagicMock

import pytest

from app.lib import marketing_films as mf

NAMES = {
    'wide_1080': 'councils-wide-1080.0123456789.mp4',
    'wide_720': 'councils-wide-720.0123456789.mp4',
    'square_720': 'councils-square-720.0123456789.mp4',
    'poster_wide_jpg': 'councils-poster-wide.0123456789.jpg',
    'poster_wide_webp': 'councils-poster-wide.abcdef0123.webp',
    'poster_square_jpg': 'councils-poster-square.0123456789.jpg',
    'poster_square_webp': 'councils-poster-square.abcdef0123.webp',
}
VIDEO = bytes(range(256)) * 40  # 10,240 bytes


@pytest.fixture
def films(app, tmp_path, monkeypatch):
    """Films on, one published film (councils) and one narrated (home), served from a local folder."""
    files = {k: {'name': v, 'bytes': 1} for k, v in NAMES.items()}
    home = {k: {'name': v.replace('councils', 'home'), 'bytes': 1} for k, v in NAMES.items()}
    home['captions_vtt'] = {'name': 'home.en-GB.0123456789.vtt', 'bytes': 1}
    manifest = tmp_path / 'marketing_films.json'
    manifest.write_text(json.dumps({'films': {
        'councils': {'duration': 43.8, 'narrated': False, 'transcript': None, 'files': files},
        'home': {'duration': 60.6, 'narrated': True, 'transcript': ['Online debate tells you who is loudest.'], 'files': home},
    }}))
    local = tmp_path / 'films'
    local.mkdir()
    (local / NAMES['wide_1080']).write_bytes(VIDEO)
    monkeypatch.setattr(mf, 'MANIFEST_PATH', str(manifest))
    monkeypatch.setattr(mf, '_local_dir', lambda: str(local))
    mf._manifest.cache_clear()
    app.config['MARKETING_FILMS_ENABLED'] = True
    app.config['MARKETING_FILMS_BASE_URL'] = None
    yield
    mf._manifest.cache_clear()


def test_no_film_while_switched_off(app):
    app.config['MARKETING_FILMS_ENABLED'] = False
    with app.test_request_context('/'):
        assert mf.get_film('councils') is None


def test_film_metadata_and_structured_data(app, films):
    with app.test_request_context('/', base_url='https://societyspeaks.io'):
        film = mf.get_film('councils')
        assert film.duration_label == '0:44'
        assert film.iso_duration == 'PT0M44S'
        assert film.url('wide_720') == f"/media/films/{NAMES['wide_720']}"
        ld = film.json_ld()
        assert ld['@type'] == 'VideoObject'
        assert ld['contentUrl'] == f"https://societyspeaks.io/media/films/{NAMES['wide_1080']}"
        assert all(u.startswith('https://') for u in ld['thumbnailUrl'])
        assert mf.get_film('tradeoffs') is None  # not in this manifest
        assert mf.get_film('home').transcript == ['Online debate tells you who is loudest.']


def test_base_url_override(app, films):
    app.config['MARKETING_FILMS_BASE_URL'] = 'https://films.example.org'
    with app.test_request_context('/'):
        assert mf.get_film('councils').url('wide_720') == f"https://films.example.org/{NAMES['wide_720']}"


def test_serves_whole_file_and_byte_ranges(client, films):
    url = f"/media/films/{NAMES['wide_1080']}"
    whole = client.get(url)
    assert whole.status_code == 200
    assert whole.data == VIDEO
    assert whole.headers['Content-Type'] == 'video/mp4'
    assert whole.headers['Cache-Control'] == mf.FILM_CACHE_CONTROL
    assert whole.headers['Accept-Ranges'] == 'bytes'
    assert 'Set-Cookie' not in whole.headers
    assert 'cookie' not in whole.headers.get('Vary', '').lower()

    part = client.get(url, headers={'Range': 'bytes=100-199'})
    assert part.status_code == 206
    assert part.data == VIDEO[100:200]
    assert part.headers['Content-Range'] == f'bytes 100-199/{len(VIDEO)}'


@pytest.mark.parametrize('name', [
    '../config.py', 'councils.mp4', 'councils-wide-1080.0123456789.mov', 'Councils-wide.0123456789.mp4',
    'councils-wide-1080.0123456789.mp4/../x',
])
def test_rejects_unexpected_names(client, films, name):
    assert client.get(f'/media/films/{name}').status_code == 404


def test_missing_file_is_404_without_object_storage(client, films):
    assert client.get(f"/media/films/{NAMES['wide_720']}").status_code == 404


def _s3(monkeypatch, client_mock):
    import app.storage_utils as su
    monkeypatch.setattr(su, 'storage_provider', lambda: 's3')
    monkeypatch.setattr(su, '_get_s3_client', lambda: client_mock)
    monkeypatch.setattr(su, '_s3_bucket', lambda: 'bucket')


def _body(data):
    body = MagicMock()
    body.iter_chunks.side_effect = lambda size: iter([data])
    return body


def test_s3_range_request_streams_a_partial_response(client, films, monkeypatch):
    s3 = MagicMock()
    s3.get_object.return_value = {'Body': _body(b'x' * 1000), 'ContentLength': 1000, 'ETag': '"e"',
                                  'ContentRange': 'bytes 0-999/5000'}
    _s3(monkeypatch, s3)
    resp = client.get(f"/media/films/{NAMES['wide_720']}", headers={'Range': 'bytes=0-999'})
    assert resp.status_code == 206
    assert resp.headers['Content-Range'] == 'bytes 0-999/5000'
    assert resp.headers['Content-Length'] == '1000'
    assert resp.data == b'x' * 1000
    s3.get_object.assert_called_once_with(Bucket='bucket', Key=f"marketing_films/{NAMES['wide_720']}", Range='bytes=0-999')


def test_s3_open_ended_and_suffix_ranges(client, films, monkeypatch):
    s3 = MagicMock()
    s3.get_object.side_effect = lambda **kw: {'Body': _body(b'y'), 'ContentLength': 1, 'ETag': '"e"', 'ContentRange': 'bytes 4999-4999/5000'}
    _s3(monkeypatch, s3)
    client.get(f"/media/films/{NAMES['wide_720']}", headers={'Range': 'bytes=4000-'})
    client.get(f"/media/films/{NAMES['wide_720']}", headers={'Range': 'bytes=-1'})
    ranges = [c.kwargs['Range'] for c in s3.get_object.call_args_list]
    assert ranges == ['bytes=4000-', 'bytes=-1']


def test_s3_head_and_errors(client, films, monkeypatch):
    from botocore.exceptions import ClientError
    s3 = MagicMock()
    s3.head_object.return_value = {'ContentLength': 5000, 'ETag': '"e"'}
    _s3(monkeypatch, s3)
    head = client.head(f"/media/films/{NAMES['wide_720']}")
    assert head.status_code == 200 and head.headers['Content-Length'] == '5000'
    s3.get_object.assert_not_called()

    s3.get_object.side_effect = ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
    assert client.get(f"/media/films/{NAMES['wide_720']}").status_code == 404

    s3.get_object.side_effect = ClientError({'Error': {'Code': 'InvalidRange'}}, 'GetObject')
    resp = client.get(f"/media/films/{NAMES['wide_720']}", headers={'Range': 'bytes=9000-'})
    assert resp.status_code == 416
    assert resp.headers['Content-Range'] == 'bytes */5000'


def test_page_shows_the_film_with_structured_data(client, db, films):
    html = client.get('/consultations').get_data(as_text=True)
    assert 'data-film="councils"' in html
    assert 'js/film_player.js' in html
    assert 'Read what the film shows' in html
    blocks = [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]
    video = [b for b in blocks if b.get('@type') == 'VideoObject']
    assert len(video) == 1 and video[0]['duration'] == 'PT0M44S'
    # the poster is the only thing that loads before a visitor presses play
    assert '<video' not in html
    assert 'loading="lazy"' in html


def test_page_without_the_film_keeps_its_layout(client, db, app):
    app.config['MARKETING_FILMS_ENABLED'] = False
    html = client.get('/consultations').get_data(as_text=True)
    assert 'ss-film' not in html and 'film_player.js' not in html


def test_home_hero_falls_back_to_the_image(client, db, app, films):
    html = client.get('/').get_data(as_text=True)
    assert 'data-film="home"' in html and 'hero-optimized.jpg' not in html
    assert 'fetchpriority="high"' in html
    app.config['MARKETING_FILMS_ENABLED'] = False
    html = client.get('/').get_data(as_text=True)
    assert 'data-film="home"' not in html and 'hero-optimized.jpg' in html


def test_narrated_film_carries_captions(client, db, films):
    html = client.get('/').get_data(as_text=True)
    assert 'data-captions="/media/films/home.en-GB.0123456789.vtt"' in html


def test_committed_manifest_only_names_known_films():
    with open(mf.MANIFEST_PATH, encoding='utf-8') as fh:
        manifest = json.load(fh)
    assert set(manifest['films']) <= set(mf.FILMS)
    for slug, film in manifest['films'].items():
        for f in film['files'].values():
            assert mf._FILE_NAME.match(f['name']), (slug, f['name'])


def test_publish_script_matches_the_app():
    import importlib.util
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'publish_marketing_films.py')
    spec = importlib.util.spec_from_file_location('publish_marketing_films', path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.STORAGE_PREFIX == mf.STORAGE_PREFIX
    assert script.FILM_CACHE_CONTROL == mf.FILM_CACHE_CONTROL
    assert script.CONTENT_TYPES == mf._MIME
    assert os.path.abspath(script.MANIFEST_PATH) == os.path.abspath(mf.MANIFEST_PATH)
