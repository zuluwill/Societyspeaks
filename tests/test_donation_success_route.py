from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import stripe


def _paid_donation():
    return SimpleNamespace(metadata={'purpose': 'donation'}, payment_status='paid')


def _make_fake_stripe(session_obj):
    fake = MagicMock()
    fake.checkout.Session.retrieve.return_value = session_obj
    return fake


# ---------------------------------------------------------------------------
# session_id format guard (no Stripe call made)
# ---------------------------------------------------------------------------

def test_donate_success_rejects_missing_session_id(app):
    response = app.test_client().get('/donate/success')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/donate')


def test_donate_success_rejects_invalid_session_id_prefix(app):
    response = app.test_client().get('/donate/success?session_id=bad_id')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/donate')


# ---------------------------------------------------------------------------
# Stripe returns an error
# ---------------------------------------------------------------------------

def test_donate_success_rejects_unknown_stripe_session(app):
    fake = MagicMock()
    fake.checkout.Session.retrieve.side_effect = stripe.error.InvalidRequestError(
        message='No such checkout session', param='id',
    )
    with patch('app.billing.service.get_stripe', return_value=fake):
        response = app.test_client().get('/donate/success?session_id=cs_test_unknown')

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/donate')


# ---------------------------------------------------------------------------
# purpose check — independent of payment_status
# ---------------------------------------------------------------------------

def test_donate_success_rejects_non_donation_session_even_if_paid(app):
    """A paid subscription checkout must not show the donation success page."""
    session = SimpleNamespace(
        metadata={'purpose': 'partner_subscription'},
        payment_status='paid',
    )
    with patch('app.billing.service.get_stripe', return_value=_make_fake_stripe(session)):
        response = app.test_client().get('/donate/success?session_id=cs_test_sub')

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/donate')


# ---------------------------------------------------------------------------
# payment_status check — independent of purpose
# ---------------------------------------------------------------------------

def test_donate_success_rejects_unpaid_donation_session(app):
    """Donation session with correct purpose but not yet paid (e.g. async payment pending)."""
    session = SimpleNamespace(
        metadata={'purpose': 'donation'},
        payment_status='unpaid',
    )
    with patch('app.billing.service.get_stripe', return_value=_make_fake_stripe(session)):
        response = app.test_client().get('/donate/success?session_id=cs_test_pending')

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/donate')


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_donate_success_renders_for_paid_donation_session(app):
    with patch('app.billing.service.get_stripe', return_value=_make_fake_stripe(_paid_donation())):
        response = app.test_client().get('/donate/success?session_id=cs_test_paid')

    assert response.status_code == 200
    assert 'Thank you for your support' in response.get_data(as_text=True)
