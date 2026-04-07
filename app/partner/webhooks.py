"""Outbound partner webhook queue + delivery."""
import hashlib
import hmac
import json
import uuid
from datetime import timedelta

import requests
from flask import current_app

from app import db
from app.lib.llm_utils import decrypt_api_key, encrypt_api_key
from app.lib.time import utcnow_naive
from app.models import PartnerWebhookEndpoint, PartnerWebhookDelivery

MAX_DELIVERY_ATTEMPTS = 5
DELIVERY_TIMEOUT_SECONDS = 10


def _compute_signature(payload_bytes, secret, timestamp):
    signed = f"{timestamp}.{payload_bytes.decode('utf-8')}".encode('utf-8')
    digest = hmac.new(secret.encode('utf-8'), signed, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def generate_webhook_secret():
    raw = f"sswh_{uuid.uuid4().hex}{uuid.uuid4().hex[:8]}"
    return raw, encrypt_api_key(raw), raw[-4:]


def _endpoint_secret(endpoint):
    return decrypt_api_key(endpoint.encrypted_signing_secret)


def enqueue_partner_event(partner_id, event_type, data, event_id=None):
    """Fan-out one logical event to matching active partner webhook endpoints."""
    event_id = event_id or f"evt_{uuid.uuid4().hex}"
    now = utcnow_naive()
    endpoints = PartnerWebhookEndpoint.query.filter_by(
        partner_id=partner_id,
        status='active',
    ).all()
    created = 0
    for endpoint in endpoints:
        if event_type not in (endpoint.event_types or []):
            continue
        payload = {
            'id': event_id,
            'type': event_type,
            'created_at': now.isoformat(),
            'data': data,
        }
        delivery = PartnerWebhookDelivery(
            endpoint_id=endpoint.id,
            partner_id=partner_id,
            event_id=event_id,
            event_type=event_type,
            payload_json=payload,
            status='pending',
            attempt_count=0,
            next_attempt_at=now,
        )
        db.session.add(delivery)
        created += 1
    if created:
        db.session.commit()
    return created


def _mark_delivery_retry(delivery, message, status_code=None, response_body=None):
    delivery.attempt_count = int(delivery.attempt_count or 0) + 1
    delivery.last_http_status = status_code
    delivery.last_response_body = (response_body or '')[:2000] if response_body else None
    delivery.last_error = (message or '')[:500] if message else None
    if delivery.attempt_count >= MAX_DELIVERY_ATTEMPTS:
        delivery.status = 'failed'
        delivery.next_attempt_at = None
    else:
        delay_minutes = 2 ** max(0, delivery.attempt_count - 1)
        delivery.status = 'retrying'
        delivery.next_attempt_at = utcnow_naive() + timedelta(minutes=delay_minutes)


def _deliver_one(delivery):
    try:
        _deliver_one_unsafe(delivery)
    except Exception as exc:
        # Unhandled errors (e.g. decrypt failure) must not abort the caller's
        # loop; treat as a transient failure so the row is retried or exhausted.
        _mark_delivery_retry(delivery, f"internal_error:{exc}")


def _deliver_one_unsafe(delivery):
    endpoint = db.session.get(PartnerWebhookEndpoint, delivery.endpoint_id)
    if not endpoint or endpoint.status != 'active':
        delivery.status = 'failed'
        delivery.last_error = 'endpoint_inactive'
        delivery.next_attempt_at = None
        return

    payload_str = json.dumps(delivery.payload_json, sort_keys=True, separators=(',', ':'))
    payload_bytes = payload_str.encode('utf-8')
    timestamp = str(int(utcnow_naive().timestamp()))
    secret = _endpoint_secret(endpoint)
    signature = _compute_signature(payload_bytes, secret, timestamp)

    headers = {
        'Content-Type': 'application/json',
        'X-SocietySpeaks-Event': delivery.event_type,
        'X-SocietySpeaks-Event-Id': delivery.event_id,
        'X-SocietySpeaks-Timestamp': timestamp,
        'X-SocietySpeaks-Signature': signature,
    }

    try:
        resp = requests.post(
            endpoint.url,
            data=payload_bytes,
            headers=headers,
            timeout=DELIVERY_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        _mark_delivery_retry(delivery, f"network_error:{exc}")
        return

    if 200 <= resp.status_code < 300:
        now = utcnow_naive()
        delivery.status = 'delivered'
        delivery.delivered_at = now
        delivery.next_attempt_at = None
        delivery.attempt_count = int(delivery.attempt_count or 0) + 1
        delivery.last_http_status = resp.status_code
        delivery.last_response_body = (resp.text or '')[:2000]
        delivery.last_error = None
        endpoint.last_delivery_at = now
        endpoint.last_error = None
        return

    _mark_delivery_retry(
        delivery,
        message=f"http_{resp.status_code}",
        status_code=resp.status_code,
        response_body=resp.text,
    )
    endpoint.last_error = f"http_{resp.status_code}"


def process_pending_webhook_deliveries(limit=100):
    now = utcnow_naive()
    deliveries = PartnerWebhookDelivery.query.filter(
        PartnerWebhookDelivery.status.in_(('pending', 'retrying')),
        PartnerWebhookDelivery.next_attempt_at <= now,
    ).order_by(
        PartnerWebhookDelivery.next_attempt_at.asc(),
        PartnerWebhookDelivery.id.asc(),
    ).limit(limit).all()

    processed = 0
    for delivery in deliveries:
        _deliver_one(delivery)
        processed += 1
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    return processed


def send_test_delivery(endpoint):
    """Deliver a synthetic test event directly to a specific endpoint.

    Bypasses event_type filtering because this is an explicit user-initiated
    ping — the goal is to verify connectivity, not fan-out policy.
    """
    now = utcnow_naive()
    event_id = f"evt_test_{uuid.uuid4().hex}"
    payload = {
        'id': event_id,
        'type': 'webhook.test',
        'created_at': now.isoformat(),
        'data': {
            'message': 'Test delivery from Society Speaks partner portal.',
            'endpoint_id': endpoint.id,
        },
    }
    delivery = PartnerWebhookDelivery(
        endpoint_id=endpoint.id,
        partner_id=endpoint.partner_id,
        event_id=event_id,
        event_type='webhook.test',
        payload_json=payload,
        status='pending',
        attempt_count=0,
        next_attempt_at=now,
    )
    db.session.add(delivery)
    db.session.commit()
    # Best-effort immediate delivery; scheduler is the durable backstop.
    try:
        _deliver_one(delivery)
        db.session.commit()
    except Exception as exc:
        current_app.logger.warning("send_test_delivery immediate attempt failed: %s", exc)
    return delivery


def emit_partner_event(partner_id, event_type, data):
    """Queue a webhook event and best-effort process a small batch immediately."""
    created = enqueue_partner_event(partner_id=partner_id, event_type=event_type, data=data)
    if not created:
        return 0
    # Best-effort low-latency delivery for partner UX; scheduler is the durable backstop.
    try:
        process_pending_webhook_deliveries(limit=20)
    except Exception as exc:
        current_app.logger.warning("emit_partner_event immediate delivery failed: %s", exc)
    return created
