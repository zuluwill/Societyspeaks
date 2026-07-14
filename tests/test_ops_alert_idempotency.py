"""Regression: ops alerts must use per-attempt Resend keys.

A fingerprint-only key would 409 for 24h because the alert subject embeds a
minute timestamp (same key, different body), silencing re-alerts for an ongoing
incident. Each allowed send must therefore carry a fresh key; the in-memory
cooldown is what suppresses duplicates.
"""


def test_ops_alert_uses_per_attempt_idempotency_key(monkeypatch):
    """Two allowed sends of the identical message get distinct Resend keys."""
    import app.scheduler as scheduler
    import app.resend_client as resend_client

    captured_keys = []

    def _fake_post(api_key, payload, *args, idempotency_key=None, **kwargs):
        captured_keys.append(idempotency_key)
        return True, 'msg-id'

    monkeypatch.setattr(resend_client, 'resend_post_with_retry', _fake_post)

    # Allow delivery outside prod, disable the in-memory cooldown so the second
    # identical alert is not suppressed, and provide the Resend prerequisites.
    monkeypatch.setenv('ALLOW_EMAIL_IN_NON_PROD', '1')
    monkeypatch.setenv('OPS_ALERT_COOLDOWN_SECONDS', '0')
    monkeypatch.setenv('RESEND_API_KEY', 'test-key')
    monkeypatch.setenv('OPS_ALERT_EMAIL_TO', 'ops@example.com')
    monkeypatch.delenv('SLACK_WEBHOOK_URL', raising=False)

    scheduler._send_ops_alert('Scheduler job X has not run in 2h')
    scheduler._send_ops_alert('Scheduler job X has not run in 2h')

    assert len(captured_keys) == 2
    assert all(k and k.startswith('ops-alert:') for k in captured_keys)
    # Per-attempt: identical message, but the keys must differ so neither send
    # collides with the other inside Resend's 24h idempotency window.
    assert captured_keys[0] != captured_keys[1]
