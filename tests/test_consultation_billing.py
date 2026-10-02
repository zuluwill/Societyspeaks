"""Consultation payments: purchases, the annual plan, refunds, and webhook routing."""
import pytest
from flask import g

from app.consultations import billing, service
from app.models import Consultation, ConsultationPlan, ConsultationPurchase, Subscription, User


@pytest.fixture
def host(app, db):
    app.config['CONSULTATIONS_SELF_SERVE_ENABLED'] = True
    user = User(
        username='payer', email='payer@example.org', password='x', email_verified=True,
        stripe_customer_id='cus_1',
    )
    db.session.add(user)
    db.session.commit()
    return user


def _checkout_session(user, *, purpose=billing.PURPOSE_SINGLE, session_id='cs_1', paid=True, **extra):
    session = {
        'id': session_id,
        'object': 'checkout.session',
        'payment_status': 'paid' if paid else 'unpaid',
        'payment_intent': 'pi_1',
        'amount_subtotal': 24900,
        'currency': 'gbp',
        'customer': user.stripe_customer_id,
        'metadata': {'purpose': purpose, 'user_id': str(user.id)},
    }
    session.update(extra)
    return session


def _subscription(user, *, status='active', subscription_id='sub_1', purpose=billing.PURPOSE_ANNUAL):
    return {
        'id': subscription_id,
        'object': 'subscription',
        'status': status,
        'current_period_end': 1_800_000_000,
        'cancel_at_period_end': False,
        'metadata': {'purpose': purpose, 'user_id': str(user.id)},
    }


def _draft(host):
    consultation = service.create_consultation(host, question='What should we change first?', organisation_name='Org')
    for index in range(5):
        service.add_statement(consultation, f'We should change thing number {index} this year.')
    return consultation


# ── One-off purchases ───────────────────────────────────────────────────────

def test_a_paid_checkout_is_recorded_once_however_often_it_is_delivered(host):
    for _delivery in range(3):
        assert billing.handle_stripe_event('checkout.session.completed', _checkout_session(host)) is True

    purchase = ConsultationPurchase.query.one()
    assert purchase.amount_pence == 24900 and purchase.is_unused
    assert billing.entitlement(host) == 'purchase'


def test_an_unpaid_checkout_grants_nothing(host):
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host, paid=False))

    assert ConsultationPurchase.query.count() == 0
    assert billing.entitlement(host) is None


def test_one_purchase_takes_one_consultation_live(host):
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host))
    first, second = _draft(host), _draft(host)

    billing.go_live(first, host)

    assert first.is_live and first.covered_by == 'purchase'
    with pytest.raises(billing.BillingError):
        billing.go_live(second, host)
    assert second.is_draft


def test_a_purchase_is_not_spent_when_the_consultation_cannot_go_live(host):
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host))
    consultation = service.create_consultation(host, question='What should we change first?', organisation_name='Org')

    with pytest.raises(service.ConsultationError):
        billing.go_live(consultation, host)

    assert billing.unused_purchases(host), 'too few statements must not consume the purchase'


def test_an_unused_purchase_can_be_refunded_once(host, monkeypatch):
    refunds = []

    class _Refund:
        @staticmethod
        def create(**kwargs):
            refunds.append(kwargs)

    class _Stripe:
        Refund = _Refund

    monkeypatch.setattr(billing, 'get_stripe', lambda: _Stripe)
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host))
    purchase = ConsultationPurchase.query.one()

    billing.refund_purchase(host, purchase.id)

    assert refunds == [{
        'payment_intent': 'pi_1', 'reason': 'requested_by_customer',
        'idempotency_key': f'consultation-purchase-refund-{purchase.id}',
    }]
    assert purchase.status == 'refunded' and billing.entitlement(host) is None
    with pytest.raises(billing.BillingError):
        billing.refund_purchase(host, purchase.id)


def test_a_used_purchase_and_someone_elses_purchase_cannot_be_refunded(host, db, monkeypatch):
    monkeypatch.setattr(billing, 'get_stripe', lambda: pytest.fail('Stripe must not be called'))
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host))
    purchase = ConsultationPurchase.query.one()
    other = User(username='other', email='other@example.org', password='x')
    db.session.add(other)
    db.session.commit()

    with pytest.raises(billing.BillingError):
        billing.refund_purchase(other, purchase.id)

    billing.go_live(_draft(host), host)
    with pytest.raises(billing.BillingError):
        billing.refund_purchase(host, purchase.id)


def test_a_refund_or_dispute_made_in_stripe_revokes_the_purchase(host):
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host))

    handled = billing.handle_stripe_event('charge.refunded', {
        'id': 'ch_1', 'object': 'charge', 'payment_intent': 'pi_1', 'refunded': True,
    })

    purchase = ConsultationPurchase.query.one()
    assert handled is True and purchase.status == 'refunded' and billing.entitlement(host) is None

    billing.handle_stripe_event('charge.dispute.created', {'payment_intent': 'pi_1', 'charge': 'ch_1'})
    assert ConsultationPurchase.query.one().status == 'disputed'


# ── The annual plan ─────────────────────────────────────────────────────────

def test_the_annual_plan_takes_any_number_of_consultations_live(host):
    assert billing.handle_stripe_event('customer.subscription.created', _subscription(host)) is True

    for _n in range(3):
        consultation = _draft(host)
        billing.go_live(consultation, host)
        assert consultation.covered_by == 'plan'

    plan = ConsultationPlan.query.one()
    assert plan.grants_access and plan.current_period_end is not None
    assert ConsultationPurchase.query.count() == 0


def test_the_plan_ends_when_stripe_says_so_and_past_due_keeps_access(host):
    billing.handle_stripe_event('customer.subscription.created', _subscription(host))

    billing.handle_stripe_event('customer.subscription.updated', _subscription(host, status='past_due'))
    assert billing.entitlement(host) == 'plan'

    billing.handle_stripe_event('customer.subscription.deleted', _subscription(host, status='canceled'))
    assert billing.entitlement(host) is None


def test_a_late_event_for_an_old_subscription_does_not_end_the_current_plan(host):
    billing.handle_stripe_event('customer.subscription.created', _subscription(host, subscription_id='sub_old'))
    billing.handle_stripe_event('customer.subscription.deleted', _subscription(host, subscription_id='sub_old', status='canceled'))
    billing.handle_stripe_event('customer.subscription.created', _subscription(host, subscription_id='sub_new'))

    billing.handle_stripe_event('customer.subscription.deleted', _subscription(host, subscription_id='sub_old', status='canceled'))

    assert billing.entitlement(host) == 'plan'
    assert ConsultationPlan.query.one().stripe_subscription_id == 'sub_new'


def test_a_second_annual_checkout_is_refused(host, monkeypatch):
    monkeypatch.setattr(billing, 'get_stripe', lambda: pytest.fail('Stripe must not be called'))
    billing.handle_stripe_event('customer.subscription.created', _subscription(host))

    with pytest.raises(billing.BillingError):
        billing.create_annual_checkout(host)


# ── Keeping the products apart ──────────────────────────────────────────────

def test_consultation_billing_never_creates_briefing_access(host):
    from app.billing.service import get_active_subscription

    billing.handle_stripe_event('customer.subscription.created', _subscription(host))
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host))

    assert Subscription.query.count() == 0
    assert get_active_subscription(host) is None


def test_other_products_events_are_left_for_their_own_handlers(host):
    assert billing.handle_stripe_event('checkout.session.completed', _checkout_session(host, purpose='donation')) is False
    assert billing.handle_stripe_event(
        'customer.subscription.updated', _subscription(host, purpose='partner_subscription'),
    ) is False
    assert billing.handle_stripe_event('customer.subscription.updated', {'id': 'sub_x', 'metadata': {}}) is False
    assert billing.handle_stripe_event('charge.refunded', {'id': 'ch_x', 'object': 'charge', 'payment_intent': 'pi_other'}) is False
    assert billing.handle_stripe_event('invoice.payment_failed', {}) is False
    assert ConsultationPurchase.query.count() == 0 and ConsultationPlan.query.count() == 0


def test_the_webhook_endpoint_routes_a_consultation_payment(app, host, client, monkeypatch):
    import json

    event = {'id': 'evt_1', 'type': 'checkout.session.completed', 'data': {'object': _checkout_session(host)}}

    class _Webhook:
        @staticmethod
        def construct_event(payload, signature, secret):
            assert secret == 'whsec_test'
            return json.loads(payload)

    class _Stripe:
        Webhook = _Webhook

        class error:
            SignatureVerificationError = type('SignatureVerificationError', (Exception,), {})

    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_test'
    monkeypatch.setattr('app.billing.routes.get_stripe', lambda: _Stripe)

    response = client.post('/billing/webhook', data=json.dumps(event), headers={'Stripe-Signature': 'sig'})

    assert response.status_code == 200
    assert ConsultationPurchase.query.one().user_id == host.id


# ── Checkout and account pages ──────────────────────────────────────────────

def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
    g.pop('_login_user', None)


def test_returning_from_checkout_takes_the_consultation_live(app, host, client, monkeypatch):
    consultation = _draft(host)
    session = _checkout_session(host, metadata={
        'purpose': billing.PURPOSE_SINGLE, 'user_id': str(host.id), 'consultation_id': str(consultation.id),
    })

    class _Session:
        @staticmethod
        def retrieve(session_id):
            assert session_id == 'cs_1'
            return session

    class _Stripe:
        class checkout:
            Session = _Session

    monkeypatch.setattr('app.billing.service.get_stripe', lambda: _Stripe)
    monkeypatch.setattr('app.consultations.emails._send', lambda consultation, **kwargs: True)
    _login(client, host)

    response = client.get('/consultations/checkout/success?session_id=cs_1')

    assert response.headers['Location'].endswith(f'/consultations/{consultation.id}/share')
    assert Consultation.query.one().is_live


def test_someone_elses_checkout_session_is_not_accepted(app, host, db, client, monkeypatch):
    other = User(username='other', email='other@example.org', password='x', stripe_customer_id='cus_2')
    db.session.add(other)
    db.session.commit()
    session = _checkout_session(host)

    class _Stripe:
        class checkout:
            class Session:
                retrieve = staticmethod(lambda session_id: session)

    monkeypatch.setattr('app.billing.service.get_stripe', lambda: _Stripe)
    _login(client, other)

    assert client.get('/consultations/checkout/success?session_id=cs_1').status_code == 404
    assert ConsultationPurchase.query.count() == 0


def test_the_account_page_shows_the_plan_purchases_and_refund(app, host, client):
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host))
    _login(client, host)

    page = client.get('/consultations/account').get_data(as_text=True)

    assert '£249.00' in page and 'Not used yet' in page and 'Refund' in page
    assert 'Annual plan: £950 a year' in page
    assert 'Manage billing' in page


# ── Account deletion ────────────────────────────────────────────────────────

def test_deleting_an_account_cancels_its_plan_and_removes_its_consultations(app, host, db, monkeypatch):
    from app.models import Discussion
    from app.settings.routes import purge_user_account

    cancelled = []

    class _Subscription:
        @staticmethod
        def cancel(subscription_id):
            cancelled.append(subscription_id)

    class _Stripe:
        Subscription = _Subscription

        class Refund:
            @staticmethod
            def create(**kwargs):
                pass

        class error:
            InvalidRequestError = type('InvalidRequestError', (Exception,), {})

    monkeypatch.setattr(billing, 'get_stripe', lambda: _Stripe)
    monkeypatch.setattr('app.billing.service.get_stripe', lambda: _Stripe)
    billing.handle_stripe_event('customer.subscription.created', _subscription(host))
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host))
    consultation = _draft(host)
    discussion_id = consultation.discussion_id

    purge_user_account(host)
    db.session.commit()

    assert cancelled == ['sub_1']
    assert Consultation.query.count() == 0 and db.session.get(Discussion, discussion_id) is None
    assert ConsultationPlan.query.count() == 0
    assert ConsultationPurchase.query.one().user_id is None, 'the payment record is kept, without the person'


def test_an_account_is_not_deleted_if_its_plan_cannot_be_cancelled(app, host, db, monkeypatch):
    from app.settings.routes import purge_user_account

    class _Stripe:
        class Subscription:
            @staticmethod
            def cancel(subscription_id):
                raise RuntimeError('Stripe unreachable')

        class error:
            InvalidRequestError = type('InvalidRequestError', (Exception,), {})

    monkeypatch.setattr(billing, 'get_stripe', lambda: _Stripe)
    monkeypatch.setattr('app.billing.service.get_stripe', lambda: _Stripe)
    billing.handle_stripe_event('customer.subscription.created', _subscription(host))
    host_id = host.id

    with pytest.raises(RuntimeError):
        purge_user_account(host)
    db.session.rollback()

    assert db.session.get(User, host_id) is not None
    assert ConsultationPlan.query.one().grants_access


# ── Races and out-of-order events ───────────────────────────────────────────

def test_a_purchase_another_request_just_spent_is_not_spent_again(host, db, monkeypatch):
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host))
    purchase = ConsultationPurchase.query.one()
    first, second = _draft(host), _draft(host)
    # The second request read the purchase as unused before the first committed.
    stale = [purchase]
    billing.go_live(first, host)
    monkeypatch.setattr(billing, 'unused_purchases', lambda user: stale)

    with pytest.raises(billing.BillingError):
        billing.go_live(second, host)

    db.session.expire_all()
    assert Consultation.query.filter_by(status='live').count() == 1
    assert ConsultationPurchase.query.one().consultation_id == first.id


def test_a_purchase_being_refunded_cannot_take_a_consultation_live(host, db, monkeypatch):
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host))
    purchase = ConsultationPurchase.query.one()
    draft = _draft(host)
    seen = {}

    class _Refund:
        @staticmethod
        def create(**kwargs):
            # While Stripe is being asked, a go-live arrives in another request.
            seen['status'] = ConsultationPurchase.query.one().status
            with pytest.raises(billing.BillingError):
                billing.go_live(draft, host)

    class _Stripe:
        Refund = _Refund

    monkeypatch.setattr(billing, 'get_stripe', lambda: _Stripe)

    billing.refund_purchase(host, purchase.id)

    assert seen['status'] == 'refunding'
    assert ConsultationPurchase.query.one().status == 'refunded'
    assert Consultation.query.one().is_draft


def test_a_refund_stripe_did_not_confirm_hands_the_purchase_back(host, db, monkeypatch):
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host))
    purchase = ConsultationPurchase.query.one()

    class _Refund:
        @staticmethod
        def create(**kwargs):
            raise RuntimeError('stripe is down')

    class _Stripe:
        Refund = _Refund

    monkeypatch.setattr(billing, 'get_stripe', lambda: _Stripe)

    with pytest.raises(RuntimeError):
        billing.refund_purchase(host, purchase.id)

    assert ConsultationPurchase.query.one().status == 'paid'
    assert billing.entitlement(host) == 'purchase'


def test_a_refund_left_unfinished_is_completed_by_the_sweep(host, db, monkeypatch):
    from datetime import timedelta
    from app.lib.time import utcnow_naive

    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host))
    purchase = ConsultationPurchase.query.one()
    purchase.status = ConsultationPurchase.STATUS_REFUNDING
    db.session.commit()
    ConsultationPurchase.query.update({'updated_at': utcnow_naive() - timedelta(hours=1)})
    db.session.commit()
    asked = []

    class _Stripe:
        class Refund:
            @staticmethod
            def create(**kwargs):
                asked.append(kwargs['idempotency_key'])

        class error:
            class InvalidRequestError(Exception):
                pass

    monkeypatch.setattr(billing, 'get_stripe', lambda: _Stripe)

    assert billing.settle_pending_refunds() == 1
    assert asked == [f'consultation-purchase-refund-{purchase.id}']
    assert ConsultationPurchase.query.one().status == 'refunded'


def test_a_late_event_cannot_bring_an_ended_plan_back(host):
    billing.handle_stripe_event('customer.subscription.created', _subscription(host))
    billing.handle_stripe_event('customer.subscription.deleted', _subscription(host, status='canceled'))

    # Delivered late and out of order.
    billing.handle_stripe_event('customer.subscription.updated', _subscription(host, status='active'))

    assert billing.entitlement(host) is None


def test_a_second_subscription_does_not_replace_the_one_in_force(host):
    billing.handle_stripe_event('customer.subscription.created', _subscription(host, subscription_id='sub_1'))

    billing.handle_stripe_event('customer.subscription.created', _subscription(host, subscription_id='sub_2'))

    assert ConsultationPlan.query.one().stripe_subscription_id == 'sub_1'


def test_starting_an_annual_checkout_closes_payment_pages_left_open(app, host, db, monkeypatch):
    host.stripe_customer_id = 'cus_1'
    db.session.commit()
    expired, created = [], []

    class _Session:
        @staticmethod
        def list(**kwargs):
            assert kwargs['customer'] == 'cus_1' and kwargs['status'] == 'open'
            return {'data': [
                {'id': 'cs_open_annual', 'metadata': {'purpose': billing.PURPOSE_ANNUAL}},
                {'id': 'cs_open_single', 'metadata': {'purpose': billing.PURPOSE_SINGLE}},
            ]}

        @staticmethod
        def expire(session_id):
            expired.append(session_id)

        @staticmethod
        def create(**kwargs):
            created.append(kwargs)
            return {'id': 'cs_new'}

    class _Stripe:
        class checkout:
            Session = _Session

    class _Customer:
        id = 'cus_1'

    monkeypatch.setattr(billing, 'get_stripe', lambda: _Stripe)
    monkeypatch.setattr(billing, 'get_or_create_stripe_customer', lambda user: _Customer)

    with app.test_request_context():
        billing.create_annual_checkout(host)

    assert expired == ['cs_open_annual']
    assert len(created) == 1 and created[0]['mode'] == 'subscription'


def test_an_account_can_be_deleted_when_stripe_has_already_ended_its_plan(host, db, monkeypatch):
    billing.handle_stripe_event('customer.subscription.created', _subscription(host))

    class _Stripe:
        class error:
            class InvalidRequestError(Exception):
                pass

        class Subscription:
            @staticmethod
            def cancel(subscription_id):
                raise _Stripe.error.InvalidRequestError('No such subscription')

    monkeypatch.setattr(billing, 'get_stripe', lambda: _Stripe)

    billing.cancel_plan_now(host)

    assert billing.entitlement(host) is None


def test_deleting_an_account_refunds_a_purchase_it_never_used(app, host, db, monkeypatch):
    from app.settings.routes import purge_user_account

    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host, session_id='cs_used'))
    billing.go_live(_draft(host), host)
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host, session_id='cs_unused'))
    refunds = []

    class _Stripe:
        class Refund:
            @staticmethod
            def create(**kwargs):
                refunds.append(kwargs['idempotency_key'])

        class error:
            class InvalidRequestError(Exception):
                pass

    monkeypatch.setattr(billing, 'get_stripe', lambda: _Stripe)
    monkeypatch.setattr('app.billing.service.get_stripe', lambda: _Stripe)
    unused = ConsultationPurchase.query.filter_by(stripe_checkout_session_id='cs_unused').one()

    purge_user_account(host)
    db.session.commit()

    assert refunds == [f'consultation-purchase-refund-{unused.id}']
    statuses = {p.stripe_checkout_session_id: p.status for p in ConsultationPurchase.query.all()}
    assert statuses == {'cs_used': 'paid', 'cs_unused': 'refunded'}


def test_an_account_is_kept_when_its_unused_purchase_cannot_be_refunded(app, host, db, monkeypatch):
    from app.settings.routes import purge_user_account

    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host))

    class _Stripe:
        class Refund:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError('stripe is down')

        class error:
            class InvalidRequestError(Exception):
                pass

    monkeypatch.setattr(billing, 'get_stripe', lambda: _Stripe)
    monkeypatch.setattr('app.billing.service.get_stripe', lambda: _Stripe)

    with pytest.raises(RuntimeError):
        purge_user_account(host)
    db.session.rollback()

    assert db.session.get(User, host.id) is not None
    assert ConsultationPurchase.query.one().status == 'paid'


def test_a_refund_or_dispute_made_in_stripe_is_found_without_a_webhook(host, db, monkeypatch):
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host, session_id='cs_a', payment_intent='pi_refunded'))
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host, session_id='cs_b', payment_intent='pi_disputed'))
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host, session_id='cs_c', payment_intent='pi_fine'))
    charges = {
        'pi_refunded': {'id': 'ch_1', 'refunded': True, 'disputed': False},
        'pi_disputed': {'id': 'ch_2', 'refunded': False, 'disputed': True},
        'pi_fine': {'id': 'ch_3', 'refunded': False, 'disputed': False},
    }

    class _Stripe:
        class PaymentIntent:
            @staticmethod
            def retrieve(payment_intent_id, expand):
                assert expand == ['latest_charge.dispute']
                return {'id': payment_intent_id, 'latest_charge': charges[payment_intent_id]}

    monkeypatch.setattr(billing, 'get_stripe', lambda: _Stripe)

    assert billing.reconcile_purchases() == 2
    statuses = {p.stripe_checkout_session_id: p.status for p in ConsultationPurchase.query.all()}
    assert statuses == {'cs_a': 'refunded', 'cs_b': 'disputed', 'cs_c': 'paid'}
    assert billing.entitlement(host) == 'purchase'


def test_a_partial_refund_of_an_unused_purchase_withdraws_the_credit(host, db, monkeypatch):
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host, payment_intent='pi_part'))

    class _Stripe:
        class PaymentIntent:
            @staticmethod
            def retrieve(payment_intent_id, expand):
                return {
                    'id': payment_intent_id,
                    'latest_charge': {
                        'id': 'ch_part', 'refunded': False, 'disputed': False,
                        'amount': 24900, 'amount_refunded': 1000,
                    },
                }

    monkeypatch.setattr(billing, 'get_stripe', lambda: _Stripe)

    assert billing.reconcile_purchases() == 1
    assert ConsultationPurchase.query.one().status == 'refunded'
    assert billing.entitlement(host) is None


def test_a_dispute_the_organiser_wins_hands_an_unused_credit_back(host, db, monkeypatch):
    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host, payment_intent='pi_won'))
    billing.handle_stripe_event('charge.dispute.created', {'payment_intent': 'pi_won', 'charge': 'ch_won'})
    assert billing.entitlement(host) is None

    class _Stripe:
        class PaymentIntent:
            @staticmethod
            def retrieve(payment_intent_id, expand):
                return {
                    'id': payment_intent_id,
                    'latest_charge': {
                        'id': 'ch_won', 'refunded': False, 'disputed': True,
                        'dispute': {'status': 'won'},
                    },
                }

    monkeypatch.setattr(billing, 'get_stripe', lambda: _Stripe)

    assert billing.reconcile_purchases() == 1
    assert ConsultationPurchase.query.one().status == 'paid'
    assert billing.entitlement(host) == 'purchase'


def test_a_refund_stripe_already_completed_still_deletes_the_account(app, host, db, monkeypatch):
    from app.settings.routes import purge_user_account

    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host))
    host_id = host.id

    class _Stripe:
        class Refund:
            @staticmethod
            def create(**kwargs):
                raise _Stripe.error.InvalidRequestError('Charge has already been refunded')

        class error:
            class InvalidRequestError(Exception):
                pass

    monkeypatch.setattr(billing, 'get_stripe', lambda: _Stripe)
    monkeypatch.setattr('app.billing.service.get_stripe', lambda: _Stripe)

    purge_user_account(host)
    db.session.commit()

    assert db.session.get(User, host_id) is None
    purchase = ConsultationPurchase.query.one()
    assert purchase.status == 'refunded' and purchase.user_id is None


def test_an_account_is_kept_when_an_unused_payment_has_no_stripe_charge(app, host, db, monkeypatch):
    from app.settings.routes import purge_user_account

    billing.handle_stripe_event('checkout.session.completed', _checkout_session(host))
    purchase = ConsultationPurchase.query.one()
    purchase.stripe_payment_intent_id = None
    db.session.commit()

    class _Stripe:
        class error:
            class InvalidRequestError(Exception):
                pass

    monkeypatch.setattr(billing, 'get_stripe', lambda: _Stripe)
    monkeypatch.setattr('app.billing.service.get_stripe', lambda: _Stripe)

    with pytest.raises(billing.BillingError):
        purge_user_account(host)
    db.session.rollback()

    assert db.session.get(User, host.id) is not None
    assert ConsultationPurchase.query.one().status == 'paid'
