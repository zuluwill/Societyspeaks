from app.lib.url_utils import is_safe_external_http_url, safe_next_url


def test_safe_next_url_rejects_protocol_relative_and_absolute():
    assert safe_next_url("/dashboard") == "/dashboard"
    assert safe_next_url("//evil.example/phish") is None
    assert safe_next_url("https://evil.example/") is None


def test_is_safe_external_http_url_accepts_normal_hosts():
    assert is_safe_external_http_url("https://societyspeaks.io/daily") is True
    assert is_safe_external_http_url("http://example.com/a") is True


def test_is_safe_external_http_url_rejects_idna_poison():
    # Empty DNS label — encodings.idna raises "label empty or too long"
    # (Sentry PYTHON-FLASK-JA on flask.redirect Location encoding).
    assert is_safe_external_http_url("https://.societyspeaks.io/x") is False
    assert is_safe_external_http_url("https://foo..bar.com/") is False
    too_long_label = "a" * 64
    assert is_safe_external_http_url(f"https://{too_long_label}.com/") is False
    assert is_safe_external_http_url("javascript:alert(1)") is False
    assert is_safe_external_http_url("https://") is False
    assert is_safe_external_http_url("") is False
