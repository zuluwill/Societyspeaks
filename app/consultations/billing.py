"""Paying for consultations: one-off purchases and the annual unlimited plan.

Kept apart from the briefing ``Subscription`` tables so neither product can
entitle the other. Shares the Stripe client, customer, portal and webhook
endpoint in ``app.billing``; events are routed here by ``metadata.purpose``.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import current_app
from flask_babel import gettext as _

from app import db
from app.billing.service import (
    _get_stripe_field,
    _get_stripe_metadata,
    _stripe_call,
    get_or_create_stripe_customer,
    get_stripe,
)
from app.consultations import service
from app.lib.time import utcnow_naive
from app.lib.url_utils import route_url
from app.models import Consultation, ConsultationPlan, ConsultationPurchase, User
from app.storage_utils import get_base_url

PURPOSE_SINGLE = 'consultation_single'
PURPOSE_ANNUAL = 'consultation_annual'

_TERMINAL_SUBSCRIPTION_STATUSES = ('canceled', 'unpaid', 'incomplete_expired')
# Stripe never brings a subscription back from these.
_FINAL_SUBSCRIPTION_STATUSES = ('canceled', 'incomplete_expired')
# A refund claimed this long ago without an answer from Stripe is asked for again.
_REFUND_RETRY_AFTER = timedelta(minutes=10)
# Card disputes can be raised for about four months after payment.
_PURCHASE_RECONCILE_WINDOW = timedelta(days=120)
# One night's Stripe reads. Older purchases in the window go first, so a
# dispute near the end of the window is not stuck behind newer ones.
_PURCHASE_RECONCILE_BATCH = 500
# The merchant keeps the money. An unused purchase can be spent again.
_DISPUTE_MERCHANT_KEEPS = frozenset({'won', 'warning_closed', 'prevented'})


class BillingError(Exception):
    """A payment rule was broken. The message is safe to show the customer."""


# ── What an account is entitled to ──────────────────────────────────────────

def active_plan(user) -> Optional[ConsultationPlan]:
    plan = ConsultationPlan.query.filter_by(user_id=user.id).first()
    return plan if plan and plan.grants_access else None


def unused_purchases(user) -> list:
    return (
        ConsultationPurchase.query.filter_by(
            user_id=user.id, status=ConsultationPurchase.STATUS_PAID,
        )
        .filter(ConsultationPurchase.consumed_at.is_(None))
        .order_by(ConsultationPurchase.id.asc())
        .all()
    )


def entitlement(user) -> Optional[str]:
    """How this account may take a consultation live, or None if it must pay first."""
    if active_plan(user):
        return Consultation.COVERED_BY_PLAN
    if unused_purchases(user):
        return Consultation.COVERED_BY_PURCHASE
    if getattr(user, 'is_admin', False):
        return Consultation.COVERED_BY_COMPLIMENTARY
    return None


def _spend_one_purchase(user, consultation: Consultation) -> bool:
    """Mark one unused purchase as spent on ``consultation``.

    The update is conditional, so two requests can never spend the same
    purchase: whichever commits second matches no row and tries the next.
    """
    for purchase in unused_purchases(user):
        spent = ConsultationPurchase.query.filter(
            ConsultationPurchase.id == purchase.id,
            ConsultationPurchase.status == ConsultationPurchase.STATUS_PAID,
            ConsultationPurchase.consumed_at.is_(None),
        ).update(
            {'consumed_at': utcnow_naive(), 'consultation_id': consultation.id},
            synchronize_session=False,
        )
        if spent:
            return True
    return False


def go_live(consultation: Consultation, user) -> Consultation:
    """Publish a draft, spending a purchase when no plan covers it."""
    # Serialise on the consultation, so a double submit publishes it once and
    # spends one purchase.
    consultation = (
        Consultation.query.filter_by(id=consultation.id)
        .with_for_update()
        .populate_existing()
        .one()
    )
    blocker = service.publish_blocker(consultation)
    if blocker:
        db.session.rollback()
        raise service.ConsultationError(blocker)

    if active_plan(user):
        covered_by = Consultation.COVERED_BY_PLAN
    elif _spend_one_purchase(user, consultation):
        covered_by = Consultation.COVERED_BY_PURCHASE
    elif getattr(user, 'is_admin', False):
        covered_by = Consultation.COVERED_BY_COMPLIMENTARY
    else:
        db.session.rollback()
        raise BillingError(_('Choose a plan to take this consultation live.'))
    try:
        # One commit publishes the consultation and spends the purchase.
        return service.publish(consultation, covered_by=covered_by)
    except Exception:
        db.session.rollback()
        raise


# ── Checkout ────────────────────────────────────────────────────────────────

def _line_item(*, price_id, amount_pence, name, description, recurring=False) -> dict:
    if price_id:
        return {'quantity': 1, 'price': price_id}
    price_data = {
        'currency': 'gbp',
        'unit_amount': amount_pence,
        'tax_behavior': 'exclusive',
        'product_data': {'name': name, 'description': description},
    }
    if recurring:
        price_data['recurring'] = {'interval': 'year'}
    return {'quantity': 1, 'price_data': price_data}


def _checkout_payload(user, *, purpose: str, consultation_id: Optional[int]) -> dict:
    customer = get_or_create_stripe_customer(user)
    metadata = {'purpose': purpose, 'user_id': str(user.id)}
    if consultation_id:
        metadata['consultation_id'] = str(consultation_id)
    base_url = get_base_url()
    success_url = route_url(base_url, 'consultations.checkout_success') + '?session_id={CHECKOUT_SESSION_ID}'
    cancel_url = (
        route_url(base_url, 'consultations.go_live', consultation_id=consultation_id)
        if consultation_id else route_url(base_url, 'consultations.account')
    )
    payload = {
        'customer': customer.id,
        'payment_method_types': ['card'],
        'billing_address_collection': 'required',
        'customer_update': {'address': 'auto', 'name': 'auto'},
        'tax_id_collection': {'enabled': True},
        'success_url': success_url,
        'cancel_url': cancel_url,
        'metadata': metadata,
    }
    if current_app.config.get('STRIPE_AUTOMATIC_TAX_ENABLED'):
        payload['automatic_tax'] = {'enabled': True}
    return payload


def create_single_checkout(user, *, consultation_id: Optional[int] = None):
    """Stripe Checkout for one consultation. Issues a proper invoice."""
    s = get_stripe()
    payload = _checkout_payload(user, purpose=PURPOSE_SINGLE, consultation_id=consultation_id)
    payload.update({
        'mode': 'payment',
        'line_items': [_line_item(
            price_id=current_app.config.get('CONSULTATION_STRIPE_PRICE_SINGLE'),
            amount_pence=current_app.config['CONSULTATION_PRICE_SINGLE_PENCE'],
            name='Society Speaks consultation',
            description='One consultation: one question, one audience, one report.',
        )],
        'invoice_creation': {'enabled': True, 'invoice_data': {'metadata': payload['metadata']}},
        'payment_intent_data': {'metadata': payload['metadata']},
    })
    return _stripe_call(s.checkout.Session.create, **payload)


def _expire_open_annual_checkouts(s, customer_id: str) -> None:
    """Close payment pages this customer left open for the annual plan, so
    two tabs cannot end in two subscriptions."""
    try:
        open_sessions = _stripe_call(s.checkout.Session.list, customer=customer_id, status='open', limit=20)
        for checkout_session in _get_stripe_field(open_sessions, 'data') or []:
            if _get_stripe_metadata(checkout_session).get('purpose') == PURPOSE_ANNUAL:
                _stripe_call(s.checkout.Session.expire, _get_stripe_field(checkout_session, 'id'))
    except Exception:
        current_app.logger.warning(
            'Could not expire open annual checkouts for customer %s', customer_id, exc_info=True,
        )


def create_annual_checkout(user, *, consultation_id: Optional[int] = None):
    """Stripe Checkout for the annual unlimited plan."""
    if active_plan(user):
        raise BillingError(_('This account already has the annual plan.'))
    s = get_stripe()
    payload = _checkout_payload(user, purpose=PURPOSE_ANNUAL, consultation_id=consultation_id)
    _expire_open_annual_checkouts(s, payload['customer'])
    payload.update({
        'mode': 'subscription',
        'line_items': [_line_item(
            price_id=current_app.config.get('CONSULTATION_STRIPE_PRICE_ANNUAL'),
            amount_pence=current_app.config['CONSULTATION_PRICE_ANNUAL_PENCE'],
            name='Society Speaks consultations: annual plan',
            description='Unlimited consultations for one organisation and its own audiences.',
            recurring=True,
        )],
        'subscription_data': {'metadata': payload['metadata']},
    })
    return _stripe_call(s.checkout.Session.create, **payload)


def create_portal_session(user):
    """Stripe's customer portal: invoices, card, cancel the annual plan."""
    if not user.stripe_customer_id:
        raise BillingError(_('There is no billing history on this account yet.'))
    s = get_stripe()
    return _stripe_call(
        s.billing_portal.Session.create,
        customer=user.stripe_customer_id,
        return_url=route_url(get_base_url(), 'consultations.account'),
    )


# ── Recording what Stripe tells us ──────────────────────────────────────────

def _user_for(metadata: dict) -> Optional[User]:
    try:
        return db.session.get(User, int(metadata.get('user_id')))
    except (TypeError, ValueError):
        return None


def _as_naive_utc(timestamp) -> Optional[datetime]:
    if not timestamp:
        return None
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).replace(tzinfo=None)


def record_single_purchase(checkout_session) -> Optional[ConsultationPurchase]:
    """Record a paid one-off checkout. Safe to call any number of times."""
    if _get_stripe_field(checkout_session, 'payment_status') != 'paid':
        return None
    session_id = _get_stripe_field(checkout_session, 'id')
    existing = ConsultationPurchase.query.filter_by(stripe_checkout_session_id=session_id).first()
    if existing:
        return existing
    user = _user_for(_get_stripe_metadata(checkout_session))
    if user is None:
        current_app.logger.error('Consultation checkout %s has no known user', session_id)
        return None
    purchase = ConsultationPurchase(
        user_id=user.id,
        stripe_checkout_session_id=session_id,
        stripe_payment_intent_id=_get_stripe_field(checkout_session, 'payment_intent'),
        amount_pence=int(_get_stripe_field(checkout_session, 'amount_subtotal') or 0),
        currency=(_get_stripe_field(checkout_session, 'currency') or 'gbp')[:3],
        status=ConsultationPurchase.STATUS_PAID,
    )
    db.session.add(purchase)
    try:
        db.session.commit()
    except Exception:
        # Lost a race with a concurrent webhook for the same session.
        db.session.rollback()
        return ConsultationPurchase.query.filter_by(stripe_checkout_session_id=session_id).first()
    return purchase


def _period_end(stripe_subscription) -> Optional[datetime]:
    end = _get_stripe_field(stripe_subscription, 'current_period_end')
    if not end:
        # Newer Stripe API versions report the period on the subscription item.
        items = _get_stripe_field(stripe_subscription, 'items') or {}
        data = _get_stripe_field(items, 'data') or []
        if data:
            end = _get_stripe_field(data[0], 'current_period_end')
    return _as_naive_utc(end)


def sync_plan(stripe_subscription, *, user: Optional[User] = None) -> Optional[ConsultationPlan]:
    """Mirror a Stripe subscription onto the account's annual plan."""
    subscription_id = _get_stripe_field(stripe_subscription, 'id')
    plan = ConsultationPlan.query.filter_by(stripe_subscription_id=subscription_id).first()
    if plan is None:
        user = user or _user_for(_get_stripe_metadata(stripe_subscription))
        if user is None:
            current_app.logger.error('Consultation subscription %s has no known user', subscription_id)
            return None
        plan = ConsultationPlan.query.filter_by(user_id=user.id).first() or ConsultationPlan(user_id=user.id)
        db.session.add(plan)
    status = _get_stripe_field(stripe_subscription, 'status') or 'inactive'
    if plan.stripe_subscription_id and plan.stripe_subscription_id != subscription_id and plan.grants_access:
        # An event for some other subscription must not replace the one in force.
        if status not in _TERMINAL_SUBSCRIPTION_STATUSES:
            current_app.logger.error(
                'Account %s has a second consultation subscription %s beside %s: cancel and refund it in Stripe',
                plan.user_id, subscription_id, plan.stripe_subscription_id,
            )
        return plan
    if (
        plan.stripe_subscription_id == subscription_id
        and plan.status in _FINAL_SUBSCRIPTION_STATUSES
        and status not in _FINAL_SUBSCRIPTION_STATUSES
    ):
        # Events can arrive out of order. An ended subscription stays ended.
        return plan
    plan.stripe_subscription_id = subscription_id
    plan.status = status
    plan.current_period_end = _period_end(stripe_subscription)
    plan.cancel_at_period_end = bool(_get_stripe_field(stripe_subscription, 'cancel_at_period_end'))
    db.session.commit()
    return plan


def fulfil_checkout_session(checkout_session) -> None:
    """Apply a completed consultation checkout (webhook or success page)."""
    purpose = _get_stripe_metadata(checkout_session).get('purpose')
    if purpose == PURPOSE_SINGLE:
        record_single_purchase(checkout_session)
    elif purpose == PURPOSE_ANNUAL:
        subscription_id = _get_stripe_field(checkout_session, 'subscription')
        if subscription_id:
            s = get_stripe()
            subscription = _stripe_call(s.Subscription.retrieve, subscription_id)
            sync_plan(subscription, user=_user_for(_get_stripe_metadata(checkout_session)))


def _purchase_for_charge(charge) -> Optional[ConsultationPurchase]:
    payment_intent = _get_stripe_field(charge, 'payment_intent')
    charge_id = _get_stripe_field(charge, 'id') if _get_stripe_field(charge, 'object') == 'charge' else None
    if payment_intent:
        purchase = ConsultationPurchase.query.filter_by(stripe_payment_intent_id=payment_intent).first()
        if purchase:
            return purchase
    if charge_id:
        return ConsultationPurchase.query.filter_by(stripe_charge_id=charge_id).first()
    return None


def handle_stripe_event(event_type: str, data) -> bool:
    """Handle a webhook event if it belongs to consultations. True when it did."""
    if event_type in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
        if _get_stripe_metadata(data).get('purpose') in (PURPOSE_SINGLE, PURPOSE_ANNUAL):
            fulfil_checkout_session(data)
            return True
        return False

    if event_type.startswith('customer.subscription.'):
        if _get_stripe_metadata(data).get('purpose') == PURPOSE_ANNUAL:
            sync_plan(data)
            return True
        return False

    if event_type == 'charge.refunded':
        purchase = _purchase_for_charge(data)
        if purchase is None:
            return False
        _record_refund(purchase, data)
        purchase.stripe_charge_id = _get_stripe_field(data, 'id')
        db.session.commit()
        return True

    if event_type == 'charge.dispute.closed':
        purchase = _purchase_for_charge({
            'payment_intent': _get_stripe_field(data, 'payment_intent'),
            'id': _get_stripe_field(data, 'charge'),
            'object': 'charge',
        })
        if purchase is None:
            return False
        _record_closed_dispute(purchase, _get_stripe_field(data, 'status'))
        db.session.commit()
        return True

    if event_type == 'charge.dispute.created':
        purchase = _purchase_for_charge({
            'payment_intent': _get_stripe_field(data, 'payment_intent'),
            'id': _get_stripe_field(data, 'charge'),
            'object': 'charge',
        })
        if purchase is None:
            return False
        purchase.status = ConsultationPurchase.STATUS_DISPUTED
        db.session.commit()
        current_app.logger.warning('Consultation purchase %s disputed', purchase.id)
        return True

    return False


# ── Customer actions ────────────────────────────────────────────────────────

def refund_purchase(user, purchase_id: int) -> ConsultationPurchase:
    """Refund a purchase that has not been used. The stated rule: full refund
    any time before the consultation it pays for goes live."""
    purchase = db.session.get(ConsultationPurchase, purchase_id)
    if purchase is None or purchase.user_id != user.id:
        raise BillingError(_('That purchase is not on this account.'))
    if not purchase.is_unused:
        raise BillingError(_('This purchase has already been used or refunded.'))
    if not purchase.stripe_payment_intent_id:
        raise BillingError(_('This purchase cannot be refunded automatically. Please contact us.'))

    # Take the purchase out of use before asking Stripe for the money back, so
    # it cannot also be spent on a consultation while the refund is in flight.
    claimed = ConsultationPurchase.query.filter(
        ConsultationPurchase.id == purchase.id,
        ConsultationPurchase.status == ConsultationPurchase.STATUS_PAID,
        ConsultationPurchase.consumed_at.is_(None),
    ).update({'status': ConsultationPurchase.STATUS_REFUNDING}, synchronize_session=False)
    db.session.commit()
    if not claimed:
        raise BillingError(_('This purchase has already been used or refunded.'))

    s = get_stripe()
    try:
        _stripe_call(
            s.Refund.create,
            payment_intent=purchase.stripe_payment_intent_id,
            reason='requested_by_customer',
            # One refund per purchase, however many times the button is pressed.
            idempotency_key=f'consultation-purchase-refund-{purchase.id}',
        )
    except Exception as exc:
        if 'already been refunded' not in str(exc).lower():
            # Stripe did not confirm a refund: hand the purchase back. If the
            # refund did go through, the nightly re-read records it.
            ConsultationPurchase.query.filter_by(
                id=purchase.id, status=ConsultationPurchase.STATUS_REFUNDING,
            ).update({'status': ConsultationPurchase.STATUS_PAID}, synchronize_session=False)
            db.session.commit()
            raise
    purchase = db.session.get(ConsultationPurchase, purchase_id)
    purchase.status = ConsultationPurchase.STATUS_REFUNDED
    purchase.refunded_at = utcnow_naive()
    db.session.commit()
    return purchase


def refund_unused_purchases(user) -> int:
    """Give back every payment this account made and never used (account
    deletion). Raises if Stripe cannot confirm one, so the account is kept
    rather than deleted with the customer's money."""
    refunded = 0
    for purchase in unused_purchases(user):
        if not purchase.stripe_payment_intent_id:
            if (purchase.amount_pence or 0) > 0:
                # Money was recorded and there is no Stripe charge to refund.
                # Deleting the account would throw that payment away.
                raise BillingError(_(
                    'A payment on this account cannot be refunded automatically. '
                    'Please contact us before deleting the account.'
                ))
            continue  # nothing was charged (a fully discounted checkout)
        refund_purchase(user, purchase.id)
        refunded += 1
    return refunded


def settle_pending_refunds() -> int:
    """Finish refunds that were claimed but never confirmed (the request died
    between the claim and Stripe's answer). Called by the sweep."""
    stuck = ConsultationPurchase.query.filter(
        ConsultationPurchase.status == ConsultationPurchase.STATUS_REFUNDING,
        ConsultationPurchase.updated_at <= utcnow_naive() - _REFUND_RETRY_AFTER,
    ).all()
    if not stuck:
        return 0
    s = get_stripe()
    settled = 0
    for purchase in stuck:
        try:
            _stripe_call(
                s.Refund.create,
                payment_intent=purchase.stripe_payment_intent_id,
                reason='requested_by_customer',
                idempotency_key=f'consultation-purchase-refund-{purchase.id}',
            )
        except s.error.InvalidRequestError as exc:
            # Stripe refuses a second refund of a charge it already refunded.
            if 'already been refunded' not in str(exc).lower():
                current_app.logger.error('Refund for consultation purchase %s needs attention: %s', purchase.id, exc)
                continue
        except Exception:
            current_app.logger.warning('Refund for consultation purchase %s still pending', purchase.id, exc_info=True)
            continue
        purchase.status = ConsultationPurchase.STATUS_REFUNDED
        purchase.refunded_at = utcnow_naive()
        db.session.commit()
        settled += 1
    return settled


def cancel_plan_now(user) -> None:
    """End the annual plan immediately (account deletion)."""
    plan = ConsultationPlan.query.filter_by(user_id=user.id).first()
    if plan is None or not plan.stripe_subscription_id or not plan.grants_access:
        return
    s = get_stripe()
    try:
        _stripe_call(s.Subscription.cancel, plan.stripe_subscription_id)
    except s.error.InvalidRequestError:
        # Already gone at Stripe: there is nothing left to cancel.
        current_app.logger.info(
            'Consultation subscription %s was already cancelled at Stripe', plan.stripe_subscription_id,
        )
    plan.status = 'canceled'
    db.session.commit()


def _money(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _fully_refunded(charge) -> bool:
    if _get_stripe_field(charge, 'refunded'):
        return True
    amount = _money(_get_stripe_field(charge, 'amount'))
    refunded = _money(_get_stripe_field(charge, 'amount_refunded'))
    return amount > 0 and refunded >= amount


def _dispute_status(charge) -> Optional[str]:
    if not _get_stripe_field(charge, 'disputed'):
        return None
    dispute = _get_stripe_field(charge, 'dispute')
    if isinstance(dispute, str) or not dispute:
        return 'open'
    return _get_stripe_field(dispute, 'status') or 'open'


def _record_refund(purchase: ConsultationPurchase, charge) -> bool:
    """Mark a purchase refunded when Stripe has taken the credit back.

    A partial refund of an unused purchase withdraws the credit too: one
    purchase is one consultation, and a part-refunded one must not still go live.
    Returns whether the row changed.
    """
    fully = _fully_refunded(charge)
    refunded_amount = _money(_get_stripe_field(charge, 'amount_refunded'))
    partial_unused = refunded_amount > 0 and not fully and purchase.consumed_at is None
    if not fully and not partial_unused:
        return False
    if purchase.status == ConsultationPurchase.STATUS_REFUNDED and purchase.refunded_at:
        return False
    if purchase.consumed_at is not None:
        current_app.logger.warning(
            'Consultation purchase %s was refunded in Stripe after it was used', purchase.id,
        )
    elif partial_unused:
        current_app.logger.warning(
            'Consultation purchase %s was only partly refunded in Stripe; the unused credit is withdrawn',
            purchase.id,
        )
    purchase.status = ConsultationPurchase.STATUS_REFUNDED
    purchase.refunded_at = purchase.refunded_at or utcnow_naive()
    return True


def _record_closed_dispute(purchase: ConsultationPurchase, status: Optional[str]) -> bool:
    """Apply the outcome of a dispute. A win hands an unused credit back."""
    if status in _DISPUTE_MERCHANT_KEEPS:
        if purchase.status != ConsultationPurchase.STATUS_DISPUTED:
            return False
        purchase.status = ConsultationPurchase.STATUS_PAID
        return True
    if status == 'lost' and purchase.status != ConsultationPurchase.STATUS_REFUNDED:
        purchase.status = ConsultationPurchase.STATUS_REFUNDED
        purchase.refunded_at = purchase.refunded_at or utcnow_naive()
        return True
    return False


def reconcile_purchases() -> int:
    """Catch refunds and disputes made in Stripe that no webhook told us about."""
    s = get_stripe()
    changed = 0
    purchases = (
        ConsultationPurchase.query.filter(
            ConsultationPurchase.status.in_((
                ConsultationPurchase.STATUS_PAID, ConsultationPurchase.STATUS_DISPUTED,
            )),
            ConsultationPurchase.stripe_payment_intent_id.isnot(None),
            ConsultationPurchase.created_at >= utcnow_naive() - _PURCHASE_RECONCILE_WINDOW,
        )
        .order_by(ConsultationPurchase.created_at.asc())
        .limit(_PURCHASE_RECONCILE_BATCH + 1)
        .all()
    )
    if len(purchases) > _PURCHASE_RECONCILE_BATCH:
        current_app.logger.warning(
            'Consultation purchase reconciliation stopped after %s rows; the rest wait for the next run',
            _PURCHASE_RECONCILE_BATCH,
        )
        purchases = purchases[:_PURCHASE_RECONCILE_BATCH]
    for purchase in purchases:
        try:
            intent = _stripe_call(
                s.PaymentIntent.retrieve,
                purchase.stripe_payment_intent_id,
                expand=['latest_charge.dispute'],
            )
        except Exception:
            current_app.logger.warning(
                'Could not re-read consultation purchase %s from Stripe', purchase.id, exc_info=True,
            )
            continue
        charge = _get_stripe_field(intent, 'latest_charge')
        if not charge or isinstance(charge, str):
            continue
        before = purchase.status
        dispute_status = _dispute_status(charge)
        if dispute_status and dispute_status not in _DISPUTE_MERCHANT_KEEPS:
            if purchase.status != ConsultationPurchase.STATUS_DISPUTED:
                purchase.status = ConsultationPurchase.STATUS_DISPUTED
                current_app.logger.warning('Consultation purchase %s disputed', purchase.id)
        elif _record_refund(purchase, charge):
            pass
        elif dispute_status in _DISPUTE_MERCHANT_KEEPS:
            _record_closed_dispute(purchase, dispute_status)
        if purchase.status == before:
            continue
        purchase.stripe_charge_id = _get_stripe_field(charge, 'id') or purchase.stripe_charge_id
        db.session.commit()
        changed += 1
    return changed


def reconcile_plans() -> int:
    """Re-read every live plan from Stripe (safety net for missed webhooks)."""
    s = get_stripe()
    changed = 0
    plans = ConsultationPlan.query.filter(ConsultationPlan.stripe_subscription_id.isnot(None)).all()
    for plan in plans:
        try:
            subscription = _stripe_call(s.Subscription.retrieve, plan.stripe_subscription_id)
        except s.error.InvalidRequestError:
            if plan.grants_access:
                plan.status = 'canceled'
                db.session.commit()
                changed += 1
            continue
        before = (plan.status, plan.current_period_end, plan.cancel_at_period_end)
        sync_plan(subscription)
        if before != (plan.status, plan.current_period_end, plan.cancel_at_period_end):
            changed += 1
    return changed
