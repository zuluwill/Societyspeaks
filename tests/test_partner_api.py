"""
Tests for partner API endpoints and embed system.

Covers:
- API endpoint validation and error handling
- Origin validation on embed flag endpoint
- Partner ref sanitization
- Embed theme/font allowlisting
- API key authentication flow
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from app.lib.time import utcnow_naive


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client(app, db):
    """Flask test client with database tables created."""
    return app.test_client()


@pytest.fixture
def partner(db):
    """Create a test partner."""
    from app.models import Partner
    p = Partner(
        name='Test Publisher',
        slug='test-publisher',
        contact_email='test@example.com',
        password_hash='fakehash',
        status='active',
        billing_status='active',
        tier='starter',
    )
    db.session.add(p)
    db.session.commit()
    return p


@pytest.fixture
def partner_domain(db, partner):
    """Create a verified partner domain."""
    from app.models import PartnerDomain
    d = PartnerDomain(
        partner_id=partner.id,
        domain='example.com',
        env='live',
        verification_method='dns_txt',
        verification_token='tok_123',
        verified_at=utcnow_naive(),
    )
    db.session.add(d)
    db.session.commit()
    return d


@pytest.fixture
def discussion(db):
    """Create a test discussion with native statements."""
    from app.models import Discussion
    d = Discussion(
        title='Should cities ban cars?',
        slug='should-cities-ban-cars',
        has_native_statements=True,
        geographic_scope='global',
        partner_env='live',
    )
    db.session.add(d)
    db.session.commit()
    return d


@pytest.fixture
def statement(db, discussion):
    """Create a test statement."""
    from app.models import Statement
    s = Statement(
        discussion_id=discussion.id,
        content='Cities should prioritise pedestrians over vehicles.',
        statement_type='claim',
        is_seed=True,
        mod_status=1,
    )
    db.session.add(s)
    db.session.commit()
    return s


# ---------------------------------------------------------------------------
# Partner Ref Sanitization
# ---------------------------------------------------------------------------

class TestSanitizePartnerRef:
    """Tests for sanitize_partner_ref utility."""

    def test_none_returns_none(self, app_context):
        from app.api.utils import sanitize_partner_ref
        assert sanitize_partner_ref(None) is None

    def test_empty_string_returns_none(self, app_context):
        from app.api.utils import sanitize_partner_ref
        assert sanitize_partner_ref('') is None

    def test_valid_ref(self, app_context):
        from app.api.utils import sanitize_partner_ref
        assert sanitize_partner_ref('observer') == 'observer'

    def test_lowercases(self, app_context):
        from app.api.utils import sanitize_partner_ref
        assert sanitize_partner_ref('TheObserver') == 'theobserver'

    def test_strips_special_chars(self, app_context):
        from app.api.utils import sanitize_partner_ref
        assert sanitize_partner_ref('my_ref!@#') == 'myref'

    def test_allows_hyphens(self, app_context):
        from app.api.utils import sanitize_partner_ref
        assert sanitize_partner_ref('my-ref') == 'my-ref'

    def test_truncates_long_refs(self, app_context):
        from app.api.utils import sanitize_partner_ref
        long_ref = 'a' * 100
        result = sanitize_partner_ref(long_ref)
        assert len(result) <= 50

    def test_non_string_returns_none(self, app_context):
        from app.api.utils import sanitize_partner_ref
        assert sanitize_partner_ref(123) is None


# ---------------------------------------------------------------------------
# Origin Validation
# ---------------------------------------------------------------------------

class TestIsPartnerOriginAllowed:
    """Tests for is_partner_origin_allowed utility."""

    def test_none_origin_rejected(self, app_context):
        from app.api.utils import is_partner_origin_allowed
        assert is_partner_origin_allowed(None) is False

    def test_empty_origin_rejected(self, app_context):
        from app.api.utils import is_partner_origin_allowed
        assert is_partner_origin_allowed('') is False

    def test_verified_domain_allowed(self, app_context, partner_domain):
        from app.api.utils import is_partner_origin_allowed
        assert is_partner_origin_allowed('https://example.com') is True

    def test_unverified_domain_rejected(self, app_context, db, partner):
        from app.models import PartnerDomain
        from app.api.utils import is_partner_origin_allowed
        # Create unverified domain
        d = PartnerDomain(
            partner_id=partner.id,
            domain='unverified.com',
            env='live',
            verification_method='dns_txt',
            verification_token='tok_456',
            verified_at=None,
        )
        db.session.add(d)
        db.session.commit()
        assert is_partner_origin_allowed('https://unverified.com') is False

    def test_unknown_domain_rejected(self, app_context):
        from app.api.utils import is_partner_origin_allowed
        assert is_partner_origin_allowed('https://evil.example.com') is False


# ---------------------------------------------------------------------------
# Lookup Endpoint
# ---------------------------------------------------------------------------

class TestLookupByArticleUrl:
    """Tests for GET /api/discussions/by-article-url."""

    def test_missing_url_returns_400(self, client):
        resp = client.get('/api/discussions/by-article-url')
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['error'] == 'missing_url'

    def test_invalid_url_returns_400(self, client):
        resp = client.get('/api/discussions/by-article-url?url=not-a-url')
        assert resp.status_code == 400

    def test_no_discussion_returns_404(self, client):
        resp = client.get('/api/discussions/by-article-url?url=https://example.com/article')
        assert resp.status_code == 404
        data = resp.get_json()
        assert data['error'] == 'no_discussion'

    def test_disabled_ref_returns_403(self, client, app):
        app.config['DISABLED_PARTNER_REFS'] = ['banned-ref']
        resp = client.get(
            '/api/discussions/by-article-url?url=https://example.com&ref=banned-ref'
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data['error'] == 'partner_disabled'


# ---------------------------------------------------------------------------
# Snapshot Endpoint
# ---------------------------------------------------------------------------

class TestGetSnapshot:
    """Tests for GET /api/discussions/{id}/snapshot."""

    def test_nonexistent_discussion_returns_404(self, client):
        resp = client.get('/api/discussions/99999/snapshot')
        assert resp.status_code == 404

    def test_valid_discussion_returns_snapshot(self, client, discussion):
        resp = client.get(f'/api/discussions/{discussion.id}/snapshot')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['discussion_id'] == discussion.id
        assert data['discussion_title'] == 'Should cities ban cars?'
        assert 'participant_count' in data
        assert 'statement_count' in data
        assert 'has_analysis' in data
        assert 'consensus_url' in data

    def test_snapshot_includes_ref_in_url(self, client, discussion):
        resp = client.get(f'/api/discussions/{discussion.id}/snapshot?ref=observer')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'ref=observer' in data['consensus_url']

    def test_disabled_ref_returns_403(self, client, app, discussion):
        app.config['DISABLED_PARTNER_REFS'] = ['banned-ref']
        resp = client.get(f'/api/discussions/{discussion.id}/snapshot?ref=banned-ref')
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# oEmbed Endpoint
# ---------------------------------------------------------------------------

class TestOEmbed:
    """Tests for GET /api/oembed."""

    def test_missing_url_returns_400(self, client):
        resp = client.get('/api/oembed')
        assert resp.status_code == 400

    def test_invalid_url_returns_400(self, client):
        resp = client.get('/api/oembed?url=https://other-site.com/page')
        assert resp.status_code == 400

    def test_valid_discussion_returns_oembed(self, client, discussion, app):
        base = app.config.get('BASE_URL', 'https://societyspeaks.io')
        url = f'{base}/discussions/{discussion.id}/{discussion.slug}/consensus'
        resp = client.get(f'/api/oembed?url={url}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['type'] == 'rich'
        assert data['version'] == '1.0'
        assert 'html' in data
        assert f'/discussions/{discussion.id}/embed' in data['html']

    def test_unsupported_format_returns_501(self, client, app, discussion):
        base = app.config.get('BASE_URL', 'https://societyspeaks.io')
        url = f'{base}/discussions/{discussion.id}'
        resp = client.get(f'/api/oembed?url={url}&format=xml')
        assert resp.status_code == 501

    def test_nonexistent_discussion_returns_404(self, client, app):
        base = app.config.get('BASE_URL', 'https://societyspeaks.io')
        url = f'{base}/discussions/99999'
        resp = client.get(f'/api/oembed?url={url}')
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Flag Endpoint
# ---------------------------------------------------------------------------

class TestFlagStatementFromEmbed:
    """Tests for POST /api/embed/flag."""

    def test_missing_origin_returns_403(self, client):
        resp = client.post('/api/embed/flag', content_type='application/json')
        assert resp.status_code == 403
        data = resp.get_json()
        assert data['error'] == 'origin_required'

    def test_missing_statement_id_returns_400(self, client, partner_domain):
        resp = client.post('/api/embed/flag', json={
            'flag_reason': 'spam'
        }, headers={'Origin': 'https://example.com'})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['error'] == 'missing_statement_id'

    def test_invalid_reason_returns_400(self, client, statement, partner_domain):
        resp = client.post('/api/embed/flag', json={
            'statement_id': statement.id,
            'flag_reason': 'invalid_reason',
            'embed_fingerprint': 'test-fp-12345678'
        }, headers={'Origin': 'https://example.com'})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['error'] == 'invalid_reason'

    def test_nonexistent_statement_returns_404(self, client, partner_domain):
        resp = client.post('/api/embed/flag', json={
            'statement_id': 99999,
            'flag_reason': 'spam',
            'embed_fingerprint': 'test-fp-12345678'
        }, headers={'Origin': 'https://example.com'})
        assert resp.status_code == 404

    def test_valid_flag_returns_201(self, client, statement, partner_domain):
        resp = client.post('/api/embed/flag', json={
            'statement_id': statement.id,
            'flag_reason': 'spam',
            'embed_fingerprint': 'test-fp-12345678'
        }, headers={'Origin': 'https://example.com'})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['success'] is True

    def test_duplicate_flag_returns_409(self, client, statement, partner_domain):
        # First flag succeeds
        client.post('/api/embed/flag', json={
            'statement_id': statement.id,
            'flag_reason': 'spam',
            'embed_fingerprint': 'test-fp-12345678'
        }, headers={'Origin': 'https://example.com'})
        # Duplicate flag returns 409
        resp = client.post('/api/embed/flag', json={
            'statement_id': statement.id,
            'flag_reason': 'harassment',
            'embed_fingerprint': 'test-fp-12345678'
        }, headers={'Origin': 'https://example.com'})
        assert resp.status_code == 409
        data = resp.get_json()
        assert data['error'] == 'already_flagged'

    def test_disallowed_origin_returns_403(self, client, statement, partner_domain):
        """Flag from an origin not in the partner allowlist should be rejected."""
        resp = client.post(
            '/api/embed/flag',
            json={
                'statement_id': statement.id,
                'flag_reason': 'spam',
                'embed_fingerprint': 'test-fp-12345678'
            },
            headers={'Origin': 'https://evil-site.com'}
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data['error'] == 'origin_not_allowed'

    def test_allowed_origin_accepted(self, client, statement, partner_domain):
        """Flag from a verified partner origin should succeed."""
        resp = client.post(
            '/api/embed/flag',
            json={
                'statement_id': statement.id,
                'flag_reason': 'spam',
                'embed_fingerprint': 'test-fp-12345678'
            },
            headers={'Origin': 'https://example.com'}
        )
        assert resp.status_code == 201

    def test_disabled_ref_returns_403(self, client, app, statement):
        app.config['DISABLED_PARTNER_REFS'] = ['banned-ref']
        resp = client.post('/api/embed/flag', json={
            'statement_id': statement.id,
            'flag_reason': 'spam',
            'ref': 'banned-ref',
            'embed_fingerprint': 'test-fp-12345678'
        }, headers={'Origin': 'https://example.com'})
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Create Discussion Endpoint (authenticated)
# ---------------------------------------------------------------------------

class TestCreateDiscussion:
    """Tests for POST /api/partner/discussions."""

    def test_missing_api_key_returns_401(self, client):
        resp = client.post('/api/partner/discussions', json={
            'article_url': 'https://example.com/article',
            'title': 'Test Discussion',
            'excerpt': 'Some article excerpt text here',
        })
        assert resp.status_code == 401

    def test_browser_origin_rejected_for_create(self, client, app):
        app.config['PARTNER_API_KEYS'] = {'test-key': 'test-publisher'}
        resp = client.post(
            '/api/partner/discussions',
            json={
                'article_url': 'https://example.com/article',
                'title': 'Test Discussion',
                'seed_statements': [{'content': 'This is a valid seed statement.', 'position': 'neutral'}],
            },
            headers={'X-API-Key': 'test-key', 'Origin': 'https://example.com'}
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data['error'] == 'browser_not_allowed'

    def test_invalid_api_key_returns_401(self, client):
        resp = client.post(
            '/api/partner/discussions',
            json={
                'article_url': 'https://example.com/article',
                'title': 'Test Discussion',
                'excerpt': 'Some article excerpt text here',
            },
            headers={'X-API-Key': 'sspk_live_invalid_key_here_0000'}
        )
        assert resp.status_code == 401

    def test_missing_body_returns_400(self, client, app):
        # Use a legacy config key for simplicity
        app.config['PARTNER_API_KEYS'] = {'test-key': 'test-publisher'}
        resp = client.post(
            '/api/partner/discussions',
            content_type='application/json',
            headers={'X-API-Key': 'test-key'}
        )
        assert resp.status_code == 400

    def test_missing_article_url_returns_400(self, client, app):
        app.config['PARTNER_API_KEYS'] = {'test-key': 'test-publisher'}
        resp = client.post(
            '/api/partner/discussions',
            json={'title': 'Test'},
            headers={'X-API-Key': 'test-key'}
        )
        assert resp.status_code == 400

    def test_missing_title_returns_400(self, client, app):
        app.config['PARTNER_API_KEYS'] = {'test-key': 'test-publisher'}
        resp = client.post(
            '/api/partner/discussions',
            json={'article_url': 'https://example.com/article'},
            headers={'X-API-Key': 'test-key'}
        )
        assert resp.status_code == 400

    def test_missing_content_returns_400(self, client, app):
        """Must provide either excerpt or seed_statements."""
        app.config['PARTNER_API_KEYS'] = {'test-key': 'test-publisher'}
        resp = client.post(
            '/api/partner/discussions',
            json={
                'article_url': 'https://example.com/article',
                'title': 'Test Discussion',
            },
            headers={'X-API-Key': 'test-key'}
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['error'] == 'missing_content'

    def test_same_title_different_urls_generate_unique_slugs(self, client, app):
        """Same title across different URLs should not fail on slug collisions."""
        app.config['PARTNER_API_KEYS'] = {'test-key': 'test-publisher'}
        headers = {'X-API-Key': 'test-key'}

        payload_one = {
            'article_url': 'https://example.com/article-one',
            'title': 'Shared Headline',
            'seed_statements': [{'content': 'This is a valid seed statement for article one.', 'position': 'neutral'}],
        }
        payload_two = {
            'article_url': 'https://example.com/article-two',
            'title': 'Shared Headline',
            'seed_statements': [{'content': 'This is a valid seed statement for article two.', 'position': 'neutral'}],
        }

        first = client.post('/api/partner/discussions', json=payload_one, headers=headers)
        second = client.post('/api/partner/discussions', json=payload_two, headers=headers)

        assert first.status_code == 201
        assert second.status_code == 201
        first_data = first.get_json()
        second_data = second.get_json()
        assert first_data['discussion_id'] != second_data['discussion_id']
        assert first_data['slug'] != second_data['slug']

    def test_idempotency_key_retry_returns_same_discussion(self, client, app):
        app.config['PARTNER_API_KEYS'] = {'test-key': 'test-publisher'}
        payload = {
            'article_url': 'https://example.com/idempotent-article',
            'title': 'Idempotent Discussion',
            'seed_statements': [{'content': 'This is a valid seed statement.', 'position': 'neutral'}],
        }
        headers = {'X-API-Key': 'test-key', 'Idempotency-Key': 'idem-123'}

        first = client.post('/api/partner/discussions', json=payload, headers=headers)
        second = client.post('/api/partner/discussions', json=payload, headers=headers)

        assert first.status_code == 201
        assert second.status_code == 201

        first_data = first.get_json()
        second_data = second.get_json()
        assert first_data['discussion_id'] == second_data['discussion_id']

    def test_idempotency_key_reuse_with_different_payload_returns_409(self, client, app):
        app.config['PARTNER_API_KEYS'] = {'test-key': 'test-publisher'}
        headers = {'X-API-Key': 'test-key', 'Idempotency-Key': 'idem-456'}

        first = client.post(
            '/api/partner/discussions',
            json={
                'article_url': 'https://example.com/a',
                'title': 'First',
                'seed_statements': [{'content': 'This is a valid seed statement.', 'position': 'neutral'}],
            },
            headers=headers
        )
        second = client.post(
            '/api/partner/discussions',
            json={
                'article_url': 'https://example.com/b',
                'title': 'Second',
                'seed_statements': [{'content': 'This is a valid seed statement.', 'position': 'neutral'}],
            },
            headers=headers
        )

        assert first.status_code == 201
        assert second.status_code == 409
        assert second.get_json()['error'] == 'idempotency_key_reused'


# ---------------------------------------------------------------------------
# Embed Theme/Font Validation
# ---------------------------------------------------------------------------

class TestEmbedThemeValidation:
    """Tests for embed theme and font validation via constants."""

    def test_all_themes_have_required_keys(self):
        from app.partner.constants import EMBED_THEMES
        for theme in EMBED_THEMES:
            assert 'id' in theme
            assert 'name' in theme
            assert 'primary' in theme
            assert 'bg' in theme
            assert 'font' in theme

    def test_theme_colors_are_valid_hex(self):
        import re
        from app.partner.constants import EMBED_THEMES
        hex_pattern = re.compile(r'^[0-9a-fA-F]{6}$')
        for theme in EMBED_THEMES:
            assert hex_pattern.match(theme['primary']), f"Invalid primary for {theme['id']}"
            assert hex_pattern.match(theme['bg']), f"Invalid bg for {theme['id']}"

    def test_default_theme_exists(self):
        from app.partner.constants import EMBED_THEMES
        ids = [t['id'] for t in EMBED_THEMES]
        assert 'default' in ids

    def test_allowed_fonts_not_empty(self):
        from app.partner.constants import EMBED_ALLOWED_FONTS
        assert len(EMBED_ALLOWED_FONTS) > 0

    def test_system_ui_in_fonts(self):
        from app.partner.constants import EMBED_ALLOWED_FONTS
        assert 'system-ui' in EMBED_ALLOWED_FONTS


# ---------------------------------------------------------------------------
# API Key Utilities
# ---------------------------------------------------------------------------

class TestApiKeyUtilities:
    """Tests for partner API key generation and lookup."""

    def test_generate_test_key_has_prefix(self, app_context):
        from app.partner.keys import generate_partner_api_key
        key, key_hash, last4 = generate_partner_api_key('test')
        assert key.startswith('sspk_test_')
        assert len(key_hash) == 64  # SHA-256 hex digest
        assert len(last4) == 4
        assert last4 == key[-4:]

    def test_generate_live_key_has_prefix(self, app_context):
        from app.partner.keys import generate_partner_api_key
        key, _, _ = generate_partner_api_key('live')
        assert key.startswith('sspk_live_')

    def test_invalid_env_raises(self, app_context):
        from app.partner.keys import generate_partner_api_key
        with pytest.raises(ValueError):
            generate_partner_api_key('staging')

    def test_parse_key_env(self, app_context):
        from app.partner.keys import parse_key_env
        assert parse_key_env('sspk_test_abc123') == 'test'
        assert parse_key_env('sspk_live_abc123') == 'live'
        assert parse_key_env('random_key') is None
        assert parse_key_env('') is None
        assert parse_key_env(None) is None

    def test_hash_is_deterministic(self, app_context):
        from app.partner.keys import hash_partner_api_key
        h1 = hash_partner_api_key('sspk_test_abc')
        h2 = hash_partner_api_key('sspk_test_abc')
        assert h1 == h2

    def test_hash_different_keys_differ(self, app_context):
        from app.partner.keys import hash_partner_api_key
        h1 = hash_partner_api_key('sspk_test_abc')
        h2 = hash_partner_api_key('sspk_test_xyz')
        assert h1 != h2

    def test_hash_empty_raises(self, app_context):
        from app.partner.keys import hash_partner_api_key
        with pytest.raises(ValueError):
            hash_partner_api_key('')

    def test_find_returns_none_for_invalid_key(self, app_context, db):
        from app.partner.keys import find_partner_api_key
        record, partner, env = find_partner_api_key('sspk_test_doesnotexist')
        assert record is None
        assert partner is None
        assert env is None

    def test_find_returns_none_for_empty_key(self, app_context, db):
        from app.partner.keys import find_partner_api_key
        record, partner, env = find_partner_api_key('')
        assert record is None


# ---------------------------------------------------------------------------
# Embed Route
# ---------------------------------------------------------------------------

class TestEmbedRoute:
    """Tests for GET /discussions/{id}/embed."""

    def test_nonexistent_discussion_returns_404(self, client):
        resp = client.get('/discussions/99999/embed')
        assert resp.status_code == 404

    def test_valid_discussion_returns_200(self, client, discussion, statement):
        resp = client.get(f'/discussions/{discussion.id}/embed')
        assert resp.status_code == 200
        assert b'Should cities ban cars?' in resp.data

    def test_embed_has_csp_header(self, client, discussion):
        resp = client.get(f'/discussions/{discussion.id}/embed')
        csp = resp.headers.get('Content-Security-Policy', '')
        assert 'frame-ancestors' in csp
        assert 'object-src' in csp

    def test_embed_no_xframe_options(self, client, discussion):
        """X-Frame-Options should be removed to allow CSP frame-ancestors."""
        resp = client.get(f'/discussions/{discussion.id}/embed')
        assert 'X-Frame-Options' not in resp.headers

    def test_invalid_theme_falls_back_to_default(self, client, discussion):
        resp = client.get(f'/discussions/{discussion.id}/embed?theme=nonexistent')
        assert resp.status_code == 200
        # Default primary color should be present
        assert b'1e40af' in resp.data

    def test_invalid_hex_color_falls_back(self, client, discussion):
        resp = client.get(f'/discussions/{discussion.id}/embed?primary=xyz123')
        assert resp.status_code == 200
        # Should fall back to default
        assert b'1e40af' in resp.data

    def test_invalid_font_is_ignored(self, client, discussion):
        resp = client.get(f'/discussions/{discussion.id}/embed?font=Comic%20Sans')
        assert resp.status_code == 200
        # Comic Sans should not appear — should use default
        assert b'Comic Sans' not in resp.data

    def test_disabled_ref_returns_403(self, client, app, discussion):
        app.config['DISABLED_PARTNER_REFS'] = ['banned']
        resp = client.get(f'/discussions/{discussion.id}/embed?ref=banned')
        assert resp.status_code == 403

    def test_embed_disabled_returns_503(self, client, app, discussion):
        app.config['EMBED_ENABLED'] = False
        resp = client.get(f'/discussions/{discussion.id}/embed')
        assert resp.status_code == 503
