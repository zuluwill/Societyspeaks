import hashlib
import hmac
import time

import pytest

from sdk.python.societyspeaks_partner import PartnerApiError, SocietyspeaksPartnerClient


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {"Content-Type": "application/json"}

    def json(self):
        return self._payload

    @property
    def text(self):
        return str(self._payload)


def test_create_discussion_sends_embed_submission_flag_and_idempotency(monkeypatch):
    captured = {}

    def _fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        captured.update(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "json": json or {},
                "params": params,
                "timeout": timeout,
            }
        )
        return _FakeResponse(201, {"discussion_id": 42})

    monkeypatch.setattr("sdk.python.societyspeaks_partner.requests.request", _fake_request)
    client = SocietyspeaksPartnerClient("https://societyspeaks.io", "sspk_live_test")

    result = client.create_discussion(
        title="Test discussion",
        external_id="observer-cms-1",
        seed_statements=[{"content": "This is a valid seed statement.", "position": "neutral"}],
        embed_statement_submissions_enabled=True,
        idempotency_key="idem-fixed",
    )

    assert result["discussion_id"] == 42
    assert captured["method"] == "POST"
    assert captured["url"] == "https://societyspeaks.io/api/partner/discussions"
    assert captured["headers"]["Idempotency-Key"] == "idem-fixed"
    assert captured["json"]["embed_statement_submissions_enabled"] is True


def test_patch_discussion_requires_at_least_one_field():
    client = SocietyspeaksPartnerClient("https://societyspeaks.io", "sspk_live_test")
    with pytest.raises(ValueError):
        client.patch_discussion(123)


def test_partner_api_error_includes_retry_after(monkeypatch):
    def _fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        return _FakeResponse(
            429,
            {"error": "rate_limited", "message": "Slow down"},
            headers={"Content-Type": "application/json", "Retry-After": "60"},
        )

    monkeypatch.setattr("sdk.python.societyspeaks_partner.requests.request", _fake_request)
    client = SocietyspeaksPartnerClient("https://societyspeaks.io", "sspk_live_test")

    with pytest.raises(PartnerApiError) as err:
        client.list_discussions()
    assert err.value.retry_after == 60


def test_verify_webhook_signature_valid(monkeypatch):
    fixed_now = 1_700_000_000
    monkeypatch.setattr("sdk.python.societyspeaks_partner.time.time", lambda: fixed_now)

    body = b'{"id":"evt_123","type":"discussion.updated"}'
    ts = str(fixed_now)
    secret = "sswh_test_secret"
    payload = f"{ts}.".encode() + body
    sig = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    assert SocietyspeaksPartnerClient.verify_webhook_signature(
        raw_body=body,
        signature_header=sig,
        timestamp_header=ts,
        secret=secret,
    )


def test_verify_webhook_signature_invalid_signature(monkeypatch):
    fixed_now = 1_700_000_000
    monkeypatch.setattr("sdk.python.societyspeaks_partner.time.time", lambda: fixed_now)
    assert SocietyspeaksPartnerClient.verify_webhook_signature(
        raw_body=b"{}",
        signature_header="sha256=deadbeef",
        timestamp_header=str(fixed_now),
        secret="sswh_test_secret",
    ) is False


def test_verify_webhook_signature_rejects_stale_timestamp(monkeypatch):
    fixed_now = 1_700_000_000
    monkeypatch.setattr("sdk.python.societyspeaks_partner.time.time", lambda: fixed_now)
    stale_ts = str(fixed_now - 301)
    with pytest.raises(ValueError):
        SocietyspeaksPartnerClient.verify_webhook_signature(
            raw_body=b"{}",
            signature_header="sha256=deadbeef",
            timestamp_header=stale_ts,
            secret="sswh_test_secret",
            tolerance_seconds=300,
        )


def test_verify_webhook_signature_rejects_malformed_timestamp():
    with pytest.raises(ValueError):
        SocietyspeaksPartnerClient.verify_webhook_signature(
            raw_body=b"{}",
            signature_header="sha256=deadbeef",
            timestamp_header="not-a-timestamp",
            secret="sswh_test_secret",
        )
