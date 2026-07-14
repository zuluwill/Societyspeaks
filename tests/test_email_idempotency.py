"""Unit tests for Resend idempotency key helpers."""
from app.lib.email_idempotency import (
    content_fingerprint,
    ensure_email_idempotency,
    scoped_entity_ref,
    send_attempt_entity_ref,
    token_entity_ref,
    url_token_segment,
)


def test_safe_entity_id_fingerprints_unicode_and_long_names():
    # Accented / emoji org names must not land raw in the Idempotency-Key
    # (requests encodes headers as latin-1).
    ref = token_entity_ref('org-invite', 'Café 🚀 Corp', 'invite-token')
    assert 'Café' not in ref
    assert '🚀' not in ref
    assert ref.startswith('org-invite:')
    assert content_fingerprint(['Café 🚀 Corp']) in ref

    # Plain numeric ids stay readable.
    import hashlib
    assert token_entity_ref('magic-login', 99, 'tok') == (
        f"magic-login:99:{hashlib.sha256(b'tok').hexdigest()[:32]}"
    )


def test_token_entity_ref_hashes_full_token_not_prefix():
    from itsdangerous import URLSafeSerializer
    from datetime import datetime

    s = URLSafeSerializer('secret')
    t1 = s.dumps(
        {'user_id': 99, 'iat': datetime(2026, 7, 14, 12, 0, 0).isoformat()},
        salt='magic-login-salt',
    )
    t2 = s.dumps(
        {'user_id': 99, 'iat': datetime(2026, 7, 14, 12, 1, 0).isoformat()},
        salt='magic-login-salt',
    )
    assert t1[:16] == t2[:16]
    assert token_entity_ref('magic-login', 99, t1) != token_entity_ref(
        'magic-login', 99, t2
    )
    assert token_entity_ref('magic-login', 99, t1) == token_entity_ref(
        'magic-login', 99, t1
    )


def test_send_attempt_entity_ref_unique_each_call():
    a = send_attempt_entity_ref('password-reset', 1)
    b = send_attempt_entity_ref('password-reset', 1)
    assert a != b
    assert a.startswith('password-reset:1:')


def test_ensure_email_idempotency_prefers_explicit_then_header_then_new():
    data, key = ensure_email_idempotency(
        {'to': ['a@b.com']}, idempotency_key='explicit-key'
    )
    assert key == 'explicit-key'
    assert data['headers']['X-Entity-Ref-ID'] == 'explicit-key'

    data2, key2 = ensure_email_idempotency(
        {'to': ['a@b.com'], 'headers': {'X-Entity-Ref-ID': 'from-header'}}
    )
    assert key2 == 'from-header'

    data3, key3 = ensure_email_idempotency({'to': ['a@b.com']})
    assert key3.startswith('send:')
    assert data3['headers']['X-Entity-Ref-ID'] == key3


def test_url_token_segment_strips_query():
    assert (
        url_token_segment(
            'https://societyspeaks.io/auth/login/magic-link/tok.abc?next=%2Fx'
        )
        == 'tok.abc'
    )


def test_content_fingerprint_and_scoped_ref():
    assert content_fingerprint([1, 2, 3]) == content_fingerprint(['1', '2', '3'])
    assert scoped_entity_ref('brief', 9, 4) == 'brief:9:4'
