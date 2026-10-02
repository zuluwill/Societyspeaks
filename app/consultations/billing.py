"""Paying for consultations: a live trial, 30-day passes and the annual plan.

Kept apart from the briefing ``Subscription`` tables so neither product can
entitle the other. Shares the Stripe client, customer, portal and webhook
endpoint in ``app.billing``; events are routed here by ``metadata.purpose``.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import current_app
from flask_babel import format_date, gettext as _
from sqlalchemy.exc import IntegrityError

from app import db
from app.billing.service import (
    _get_stripe_field,
    _get_stripe_metadata,
    _stripe_call,
    get_or_create_stripe_customer,
    get_stripe,
)
from app.consultations import service
from app.lib.email_normalize import normalize_trial_email
from app.lib.time import utcnow_naive
from app.lib.url_utils import route_url
from app.models import Consultation, ConsultationPlan, ConsultationPurchase, ConsultationTrial, User
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
# The merchant keeps the money. A pass whose window has not ended can be used again.
_DISPUTE_MERCHANT_KEEPS = frozenset({'won', 'warning_closed', 'prevented'})
# The next pass can be bought in the last days of the open one, so a
# consultation need not close while the host waits for the first to end.
_PASS_RENEWAL_WINDOW = timedelta(days=7)
# Personal inboxes are not an organisation. A second trial from one of these
# domains is allowed; a second trial from the same address is not.
_FREE_EMAIL_DOMAINS = frozenset({
    'gmail.com', 'googlemail.com', 'outlook.com', 'hotmail.com', 'hotmail.co.uk',
    'live.com', 'live.co.uk', 'msn.com', 'yahoo.com', 'yahoo.co.uk', 'ymail.com',
    'icloud.com', 'me.com', 'mac.com', 'proton.me', 'protonmail.com', 'pm.me',
    'aol.com', 'gmx.com', 'gmx.co.uk', 'mail.com', 'zoho.com', 'fastmail.com',
    'hey.com', 'tutanota.com', 'tuta.com', 'duck.com',
})


class BillingError(Exception):
    """A payment rule was broken. The message is safe to show the customer."""


# ── What an account is entitled to ──────────────────────────────────────────

def active_plan(user) -> Optional[ConsultationPlan]:
    plan = ConsultationPlan.query.filter_by(user_id=user.id).first()
    return plan if plan and plan.grants_access else None


def pass_days() -> int:
    return int(current_app.config.get('CONSULTATION_PASS_DAYS', 30))


def unused_purchases(user) -> list:
    """Paid passes that have not yet taken a consultation live, so they can be refunded."""
    return (
        ConsultationPurchase.query.filter_by(
            user_id=user.id, status=ConsultationPurchase.STATUS_PAID,
        )
        .filter(
            ConsultationPurchase.consumed_at.is_(None),
            ConsultationPurchase.credited_at.is_(None),
        )
        .order_by(ConsultationPurchase.id.asc())
        .all()
    )


def active_passes(user) -> list:
    """Paid passes inside their window, soonest to expire first.

    A pass whose window has not started is excluded: it was bought while
    another pass was still open, and it begins when that one ends.
    """
    now = utcnow_naive()
    return (
        ConsultationPurchase.query.filter_by(
            user_id=user.id, status=ConsultationPurchase.STATUS_PAID,
        )
        .filter(
            ConsultationPurchase.valid_until.isnot(None),
            ConsultationPurchase.valid_until > now,
            db.or_(
                ConsultationPurchase.valid_from.is_(None),
                ConsultationPurchase.valid_from <= now,
            ),
        )
        .order_by(ConsultationPurchase.valid_until.asc(), ConsultationPurchase.id.asc())
        .all()
    )


def open_pass(user) -> Optional[ConsultationPurchase]:
    """The paid pass that has not ended, including one that has not started."""
    now = utcnow_naive()
    return (
        ConsultationPurchase.query.filter_by(
            user_id=user.id, status=ConsultationPurchase.STATUS_PAID,
        )
        .filter(
            ConsultationPurchase.valid_until.isnot(None),
            ConsultationPurchase.valid_until > now,
        )
        .order_by(ConsultationPurchase.valid_until.desc(), ConsultationPurchase.id.desc())
        .first()
    )


def active_pass(user) -> Optional[ConsultationPurchase]:
    passes = active_passes(user)
    return passes[0] if passes else None


def active_trial(user) -> Optional[ConsultationTrial]:
    trial = ConsultationTrial.query.filter_by(user_id=user.id).first()
    return trial if trial and trial.is_open else None


def _email_domain(email: str) -> str:
    parts = (email or '').rsplit('@', 1)
    return parts[1].strip().lower() if len(parts) == 2 else ''


def trial_domain_key(email: str) -> Optional[str]:
    """The work domain recorded with a trial, or None for a personal inbox.

    A repeated work domain is an abuse signal. It does not refuse the trial.
    """
    domain = _email_domain(email)
    if not domain or domain in _FREE_EMAIL_DOMAINS:
        return None
    return domain


def work_domain_repeat(user) -> bool:
    """True when another account at this work domain has already started a trial."""
    domain = trial_domain_key(getattr(user, 'email', None) or '')
    if not domain:
        return False
    return (
        ConsultationTrial.query.filter(
            ConsultationTrial.domain == domain,
            ConsultationTrial.user_id != user.id,
        ).count()
        > 0
    )


def trial_already_used(user) -> bool:
    """True when this verified email has already had a trial."""
    if ConsultationTrial.query.filter_by(user_id=user.id).first():
        return True
    email_key = normalize_trial_email(getattr(user, 'email', None))
    return bool(email_key and ConsultationTrial.query.filter_by(email_key=email_key).first())


def trial_available(user) -> bool:
    """Whether the next go-live may start this account's free trial.

    One trial per verified email. An account that has already paid does not
    get a trial afterwards. A colleague at the same organisation may still
    start their own.
    """
    if not getattr(user, 'email_verified', False):
        return False
    if ConsultationPurchase.query.filter_by(user_id=user.id).first():
        return False
    if ConsultationPlan.query.filter_by(user_id=user.id).first():
        return False
    if not normalize_trial_email(getattr(user, 'email', None)):
        return False
    from app.lib.trial_abuse import is_disposable_email
    if is_disposable_email(user.email):
        return False
    return not trial_already_used(user)


def acquisition_source() -> str:
    """The campaign on the link when a trial starts, or ``direct``.

    Only letters, numbers and ``._-`` are kept, so a question or an email
    address in the link cannot be stored.
    """
    raw = ''
    try:
        from flask import has_request_context
        if has_request_context():
            from app.lib.utm import peek_utms
            raw = peek_utms().get('utm_source') or ''
    except Exception:
        raw = ''
    cleaned = ''.join(ch for ch in raw.strip().lower() if ch.isalnum() or ch in '._-')[:80]
    return cleaned or 'direct'


def start_trial(user) -> ConsultationTrial:
    now = utcnow_naive()
    days = int(current_app.config.get('CONSULTATION_TRIAL_DAYS', 14))
    trial = ConsultationTrial(
        user_id=user.id,
        email_key=normalize_trial_email(user.email),
        domain=trial_domain_key(user.email or ''),
        acquisition_source=acquisition_source(),
        started_at=now,
        ends_at=now + timedelta(days=days),
    )
    db.session.add(trial)
    db.session.flush()
    if work_domain_repeat(user):
        current_app.logger.warning(
            'Consultation trial for user %s repeats work domain %s', user.id, trial.domain,
        )
    return trial


def entitlement(user) -> Optional[str]:
    """How this account may take a consultation live, or None if it must pay first.

    A site admin is complimentary, ahead of any pass, so trying the product
    does not spend a payment. A live trial is the same kind of access as a pass.
    """
    if active_plan(user):
        return Consultation.COVERED_BY_PLAN
    if getattr(user, 'is_admin', False):
        return Consultation.COVERED_BY_COMPLIMENTARY
    if active_passes(user):
        return Consultation.COVERED_BY_PURCHASE
    if active_trial(user):
        return Consultation.COVERED_BY_TRIAL
    return None


def access_ends_at(user) -> Optional[datetime]:
    """When this account's consultations must close, or None if access does not end.

    Complimentary access is not capped. A plan, a trial and a pass each end,
    and the latest of a trial and a pass is what a consultation may run until.
    """
    if user is None or getattr(user, 'is_admin', False):
        return None
    plan = active_plan(user)
    if plan is not None:
        # A plan that renews does not end. A cancelled one runs to the end of the paid year.
        return plan.current_period_end if plan.cancel_at_period_end else None
    ends = []
    trial = active_trial(user)
    if trial is not None:
        ends.append(trial.ends_at)
    purchase = open_pass(user)
    if purchase is not None and purchase.valid_until is not None:
        ends.append(purchase.valid_until)
    if not ends:
        return None
    return max(ends)


def access_lapsed(consultation: Consultation) -> bool:
    """True when a live consultation's account no longer has access.

    Complimentary consultations are left open. The sweep closes the rest and
    builds the report, even if the closing date was set further out.
    """
    if not consultation.is_live:
        return False
    if consultation.covered_by == Consultation.COVERED_BY_COMPLIMENTARY:
        return False
    if _paid_before_passes(consultation):
        return False
    user = consultation.owner
    if user is None or getattr(user, 'is_admin', False):
        return False
    return entitlement(user) is None


def _paid_before_passes(consultation: Consultation) -> bool:
    """Paid for as a single consultation, before a payment became a 30-day
    window. It runs to its own closing date, as it was sold."""
    return (
        consultation.covered_by == Consultation.COVERED_BY_PURCHASE
        and consultation.covered_by_purchase_id is None
    )


def may_keep_open(consultation: Consultation, user) -> bool:
    """Whether the host may extend or reopen this consultation."""
    if consultation.covered_by == Consultation.COVERED_BY_COMPLIMENTARY:
        return True
    if consultation.is_live and _paid_before_passes(consultation):
        return True
    return entitlement(user) is not None


def mark_passes_in_use(user) -> bool:
    """Record a pass as used once it is what keeps a consultation open.

    A consultation taken live on the trial, or reopened later, can be running
    on a pass it was never attached to at go-live. That pass has been used, so
    it is no longer refundable. The caller commits.
    """
    if user is None or entitlement(user) != Consultation.COVERED_BY_PURCHASE:
        return False
    current = {purchase.id for purchase in active_passes(user)}
    changed = False
    live = Consultation.query.filter_by(owner_user_id=user.id, status=Consultation.STATUS_LIVE).all()
    for consultation in live:
        if consultation.covered_by == Consultation.COVERED_BY_COMPLIMENTARY or _paid_before_passes(consultation):
            continue
        if consultation.covered_by_purchase_id in current:
            continue
        if _cover_with_pass(user, consultation):
            consultation.covered_by = Consultation.COVERED_BY_PURCHASE
            changed = True
    return changed


def _window_ending_at(user, end: datetime):
    """The trial, pass or plan whose end is ``end``, so a warning is sent once."""
    plan = active_plan(user)
    if plan is not None and plan.current_period_end == end:
        return plan
    purchase = open_pass(user)
    if purchase is not None and purchase.valid_until == end:
        return purchase
    trial = active_trial(user)
    if trial is not None and trial.ends_at == end:
        return trial
    return None


def warn_expiring_access() -> int:
    """Email a host once, two days before access ends, if a consultation is open.

    Paying moves the end date onto a new window, which has not been warned yet,
    so the reminder follows the access they actually have.
    """
    now = utcnow_naive()
    horizon = now + timedelta(days=2)
    sent = 0
    owner_ids = [
        row[0]
        for row in db.session.query(Consultation.owner_user_id)
        .filter(Consultation.status == Consultation.STATUS_LIVE)
        .distinct()
    ]
    from app.consultations import emails
    for user_id in owner_ids:
        user = db.session.get(User, user_id)
        if user is None:
            continue
        end = access_ends_at(user)
        if end is None or not now < end <= horizon:
            continue
        window = _window_ending_at(user, end)
        if window is None or window.ending_notified_at is not None:
            continue
        consultation = (
            Consultation.query.filter_by(owner_user_id=user.id, status=Consultation.STATUS_LIVE)
            .order_by(Consultation.closes_at.asc())
            .first()
        )
        # Claim the warning before sending it, so two sweeps cannot both send.
        model, window_id = type(window), window.id
        claimed = model.query.filter(
            model.id == window_id, model.ending_notified_at.is_(None),
        ).update({'ending_notified_at': now}, synchronize_session=False)
        db.session.commit()
        if not claimed:
            continue
        try:
            delivered = emails.notify_access_ending(
                user, end, question=consultation.question if consultation is not None else '',
            )
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Could not warn user %s that access is ending', user_id)
            delivered = False
        if delivered:
            sent += 1
        else:
            # Not sent: release the claim so the next sweep tries again.
            model.query.filter_by(id=window_id).update({'ending_notified_at': None}, synchronize_session=False)
            db.session.commit()
    return sent


def _cover_with_pass(user, consultation: Consultation) -> bool:
    """Attach ``consultation`` to the pass that expires soonest.

    The first consultation on a pass stamps ``consumed_at``, which is what
    ends the refund. Later consultations in the same window do not. Two
    go-lives at once may both succeed: a pass is not a single credit.
    """
    now = utcnow_naive()
    for purchase in active_passes(user):
        locked = (
            ConsultationPurchase.query.filter(
                ConsultationPurchase.id == purchase.id,
                ConsultationPurchase.status == ConsultationPurchase.STATUS_PAID,
                ConsultationPurchase.valid_until > now,
            )
            .with_for_update()
            .first()
        )
        if locked is None:
            continue
        consultation.covered_by_purchase_id = locked.id
        if locked.consumed_at is None:
            locked.consumed_at = now
        return True
    return False


def go_live(consultation: Consultation, user) -> Consultation:
    """Publish a draft, covering it with a pass when no plan does."""
    # Serialise on the consultation, so a double submit publishes it once.
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

    repeated_domain = False
    if active_plan(user):
        covered_by = Consultation.COVERED_BY_PLAN
    elif getattr(user, 'is_admin', False):
        covered_by = Consultation.COVERED_BY_COMPLIMENTARY
    elif _cover_with_pass(user, consultation):
        covered_by = Consultation.COVERED_BY_PURCHASE
    elif active_trial(user):
        covered_by = Consultation.COVERED_BY_TRIAL
    elif trial_available(user):
        repeated_domain = work_domain_repeat(user)
        try:
            start_trial(user)
        except IntegrityError:
            db.session.rollback()
            raise BillingError(_('This email address has already used the free trial.'))
        covered_by = Consultation.COVERED_BY_TRIAL
    elif trial_already_used(user):
        db.session.rollback()
        raise BillingError(_('This email address has already used the free trial.'))
    else:
        db.session.rollback()
        raise BillingError(_('Choose how you would like to pay to take this consultation live.'))
    try:
        # One commit publishes the consultation and records the pass or trial.
        # The closing date the host chose is kept. If it is later than access,
        # the sweep closes voting when access ends, unless they pay first.
        published = service.publish(consultation, covered_by=covered_by)
    except Exception:
        db.session.rollback()
        raise
    from app.consultations.analytics import capture_consultation_event
    capture_consultation_event(
        'consultation_went_live',
        user_id=user.id,
        insert_id=f'consultation_went_live:{published.id}',
        properties={
            'consultation_id': published.id,
            'covered_by': covered_by,
            'domain_repeat': repeated_domain,
        },
        durable=True,
    )
    return published


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


def pass_purchase_blocker(user) -> Optional[str]:
    """Why this account cannot buy a pass now, or None if it can.

    Refused while the annual plan is active, while a pass is waiting to start,
    and while the open pass has more than a week left, so a second tab cannot
    charge the same month twice. In its last week the next pass can be bought;
    it starts when the open one ends.
    """
    if active_plan(user):
        return _('This account already has the annual plan, which covers every consultation.')
    existing = open_pass(user)
    if existing is None:
        return None
    if existing.is_scheduled or existing.valid_until - utcnow_naive() > _PASS_RENEWAL_WINDOW:
        return _pass_already_open_message(existing)
    return None


def create_single_checkout(user, *, consultation_id: Optional[int] = None):
    """Stripe Checkout for a 30-day pass. Issues a proper invoice.

    A payment that arrives while a pass is still open is recorded as the
    following window, so the paid days never overlap.
    """
    blocker = pass_purchase_blocker(user)
    if blocker:
        raise BillingError(blocker)
    s = get_stripe()
    days = pass_days()
    payload = _checkout_payload(user, purpose=PURPOSE_SINGLE, consultation_id=consultation_id)
    _expire_open_checkouts(s, payload['customer'], PURPOSE_SINGLE)
    payload.update({
        'mode': 'payment',
        'line_items': [_line_item(
            price_id=current_app.config.get('CONSULTATION_STRIPE_PRICE_SINGLE'),
            amount_pence=current_app.config['CONSULTATION_PRICE_SINGLE_PENCE'],
            name=f'Society Speaks consultations: {days} days',
            description=(
                f'{days} days of consultations for one organisation. '
                'Each question has its own report.'
            ),
        )],
        'invoice_creation': {'enabled': True, 'invoice_data': {'metadata': payload['metadata']}},
        'payment_intent_data': {'metadata': payload['metadata']},
    })
    return _stripe_call(s.checkout.Session.create, **payload)


def _expire_open_checkouts(s, customer_id: str, purpose: str) -> None:
    """Close payment pages this customer left open for one product, so two
    tabs cannot both be paid."""
    try:
        open_sessions = _stripe_call(s.checkout.Session.list, customer=customer_id, status='open', limit=20)
        for checkout_session in _get_stripe_field(open_sessions, 'data') or []:
            if _get_stripe_metadata(checkout_session).get('purpose') == purpose:
                _stripe_call(s.checkout.Session.expire, _get_stripe_field(checkout_session, 'id'))
    except Exception:
        current_app.logger.warning(
            'Could not expire open %s checkouts for customer %s', purpose, customer_id, exc_info=True,
        )


def _pass_already_open_message(purchase: ConsultationPurchase) -> str:
    end = format_date(purchase.valid_until, 'd MMMM y')
    if purchase.is_scheduled:
        return _(
            'You already have a pass from %(start)s to %(end)s. '
            'It covers every consultation you take live in that time.',
            start=format_date(purchase.valid_from, 'd MMMM y'),
            end=end,
        )
    return _(
        'You already have a pass until %(end)s. '
        'It covers every consultation you take live before then. '
        'You can buy the next 30 days in its last week.',
        end=end,
    )


def uncredited_pass_credit(user) -> tuple:
    """Pence to take off the first annual invoice, and the passes it comes from.

    Only a pass that is still open, and has not already been credited, counts.
    The credit cannot be more than the annual price.
    """
    now = utcnow_naive()
    annual = int(current_app.config['CONSULTATION_PRICE_ANNUAL_PENCE'])
    passes = (
        ConsultationPurchase.query.filter_by(
            user_id=user.id, status=ConsultationPurchase.STATUS_PAID,
        )
        .filter(
            ConsultationPurchase.credited_at.is_(None),
            ConsultationPurchase.amount_pence > 0,
            ConsultationPurchase.valid_until.isnot(None),
            ConsultationPurchase.valid_until > now,
        )
        .order_by(ConsultationPurchase.id.asc())
        .all()
    )
    total = sum(purchase.amount_pence for purchase in passes)
    return min(total, annual), passes


def create_annual_checkout(user, *, consultation_id: Optional[int] = None):
    """Stripe Checkout for the annual unlimited plan.

    The subscription starts when checkout completes, so the paid year begins
    on the day they upgrade. An open pass is taken off that first invoice.
    """
    if active_plan(user):
        raise BillingError(_('This account already has the annual plan.'))
    s = get_stripe()
    payload = _checkout_payload(user, purpose=PURPOSE_ANNUAL, consultation_id=consultation_id)
    _expire_open_checkouts(s, payload['customer'], PURPOSE_ANNUAL)
    credit_pence, credit_passes = uncredited_pass_credit(user)
    if credit_pence > 0:
        coupon = _stripe_call(
            s.Coupon.create,
            amount_off=credit_pence,
            currency='gbp',
            duration='once',
            max_redemptions=1,
            name='30-day access credit',
            metadata={
                'purpose': 'consultation_pass_credit',
                'purchase_ids': ','.join(str(purchase.id) for purchase in credit_passes),
                'user_id': str(user.id),
            },
        )
        payload['discounts'] = [{'coupon': _get_stripe_field(coupon, 'id')}]
        payload['metadata']['pass_credit_purchase_ids'] = ','.join(
            str(purchase.id) for purchase in credit_passes
        )
    payload.update({
        'mode': 'subscription',
        'line_items': [_line_item(
            price_id=current_app.config.get('CONSULTATION_STRIPE_PRICE_ANNUAL'),
            amount_pence=current_app.config['CONSULTATION_PRICE_ANNUAL_PENCE'],
            name='Society Speaks consultations: annual plan',
            description='Unlimited consultations for one organisation and its own audiences.',
            recurring=True,
        )],
        'subscription_data': {'metadata': dict(payload['metadata'])},
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


def _lock_account(user) -> None:
    """One pass grant at a time for this account."""
    db.session.query(User).filter_by(id=user.id).with_for_update().one()


def _reflow_scheduled_passes(user_id: Optional[int]) -> None:
    """Pack passes that have not started behind whatever is still open.

    Refunding an earlier pass must not leave a gap, and must not make the
    later pass any longer than the 30 days that were paid for.
    """
    if not user_id:
        return
    now = utcnow_naive()
    current_end = (
        db.session.query(db.func.max(ConsultationPurchase.valid_until))
        .filter(
            ConsultationPurchase.user_id == user_id,
            ConsultationPurchase.status == ConsultationPurchase.STATUS_PAID,
            ConsultationPurchase.valid_until.isnot(None),
            ConsultationPurchase.valid_until > now,
            db.or_(
                ConsultationPurchase.valid_from.is_(None),
                ConsultationPurchase.valid_from <= now,
            ),
        )
        .scalar()
    )
    cursor = current_end or now
    scheduled = (
        ConsultationPurchase.query.filter(
            ConsultationPurchase.user_id == user_id,
            ConsultationPurchase.status == ConsultationPurchase.STATUS_PAID,
            ConsultationPurchase.valid_from.isnot(None),
            ConsultationPurchase.valid_from > now,
            ConsultationPurchase.valid_until.isnot(None),
        )
        .order_by(ConsultationPurchase.valid_from.asc(), ConsultationPurchase.id.asc())
        .all()
    )
    for purchase in scheduled:
        length = purchase.valid_until - purchase.valid_from
        if length <= timedelta(0):
            length = timedelta(days=pass_days())
        purchase.valid_from = cursor
        purchase.valid_until = cursor + length
        cursor = purchase.valid_until


def _next_window(user, paid_at: datetime) -> tuple:
    """When a new pass runs. It starts at payment, or when the open pass ends
    if one is already paid, so two charges never cover the same days."""
    latest_end = (
        db.session.query(db.func.max(ConsultationPurchase.valid_until))
        .filter(
            ConsultationPurchase.user_id == user.id,
            ConsultationPurchase.status == ConsultationPurchase.STATUS_PAID,
            ConsultationPurchase.valid_until.isnot(None),
            ConsultationPurchase.valid_until > paid_at,
        )
        .scalar()
    )
    start = latest_end if latest_end and latest_end > paid_at else paid_at
    # A pass bought during a trial starts when the trial ends, so the paid
    # days are not spent on days the account already has.
    trial = active_trial(user)
    if trial is not None and trial.ends_at > start:
        start = trial.ends_at
    return start, start + timedelta(days=pass_days())


def record_single_purchase(checkout_session) -> Optional[ConsultationPurchase]:
    """Record a paid 30-day pass. Safe to call any number of times.

    The window is measured from when the payment is recorded (the return from
    checkout, or the webhook, normally within seconds of payment). Setting a
    consultation up stays free. A second payment for an account that already
    has a pass starts when that pass ends.
    """
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
    _lock_account(user)
    existing = ConsultationPurchase.query.filter_by(stripe_checkout_session_id=session_id).first()
    if existing:
        return existing
    valid_from, valid_until = _next_window(user, utcnow_naive())
    purchase = ConsultationPurchase(
        user_id=user.id,
        stripe_checkout_session_id=session_id,
        stripe_payment_intent_id=_get_stripe_field(checkout_session, 'payment_intent'),
        amount_pence=int(_get_stripe_field(checkout_session, 'amount_subtotal') or 0),
        currency=(_get_stripe_field(checkout_session, 'currency') or 'gbp')[:3],
        status=ConsultationPurchase.STATUS_PAID,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    db.session.add(purchase)
    try:
        db.session.commit()
    except Exception:
        # Lost a race with a concurrent webhook for the same session.
        db.session.rollback()
        return ConsultationPurchase.query.filter_by(stripe_checkout_session_id=session_id).first()
    from app.consultations.analytics import capture_consultation_event
    capture_consultation_event(
        'consultation_pass_purchased',
        user_id=user.id,
        insert_id=f'consultation_pass_purchased:{session_id}',
        properties={'amount_pence': purchase.amount_pence, 'currency': purchase.currency},
        durable=True,
    )
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
    previous_status = plan.status
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
    if plan.grants_access and previous_status not in ConsultationPlan.ACCESS_STATUSES:
        from app.consultations.analytics import capture_consultation_event
        capture_consultation_event(
            'consultation_plan_started',
            user_id=plan.user_id,
            insert_id=f'consultation_plan_started:{subscription_id}',
            properties={'plan': 'annual'},
            durable=True,
        )
    if plan.grants_access:
        _mark_pass_credited(_get_stripe_metadata(stripe_subscription))
    return plan


def _mark_pass_credited(metadata: dict) -> None:
    """Record that the open passes were taken off the annual plan.

    Called only after the subscription is actually in force, so an abandoned
    checkout does not use up the credit.
    """
    raw = (metadata or {}).get('pass_credit_purchase_ids') or ''
    ids = [int(part) for part in str(raw).split(',') if part.strip().isdigit()]
    if not ids:
        return
    now = utcnow_naive()
    changed = False
    for purchase in ConsultationPurchase.query.filter(ConsultationPurchase.id.in_(ids)):
        if purchase.credited_at is None and purchase.status == ConsultationPurchase.STATUS_PAID:
            purchase.credited_at = now
            changed = True
    if changed:
        db.session.commit()


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
    """Refund a pass that has not been used. Full refund any time before the
    first consultation on it goes live."""
    purchase = db.session.get(ConsultationPurchase, purchase_id)
    if purchase is None or purchase.user_id != user.id:
        raise BillingError(_('That purchase is not on this account.'))
    # A pass that is keeping a consultation open has been used, even if no
    # consultation went live on it.
    if mark_passes_in_use(user):
        db.session.commit()
        db.session.refresh(purchase)
    if not purchase.is_unused:
        raise BillingError(_('This purchase has already been used or refunded.'))
    if not purchase.stripe_payment_intent_id:
        raise BillingError(_('This purchase cannot be refunded automatically. Please contact us.'))
    # An annual checkout left open may carry this pass as a discount. Close it,
    # so the pass cannot be both refunded and taken off the first year.
    if user.stripe_customer_id:
        _expire_open_checkouts(get_stripe(), user.stripe_customer_id, PURPOSE_ANNUAL)

    # Take the purchase out of use before asking Stripe for the money back, so
    # it cannot also be spent on a consultation while the refund is in flight.
    claimed = ConsultationPurchase.query.filter(
        ConsultationPurchase.id == purchase.id,
        ConsultationPurchase.status == ConsultationPurchase.STATUS_PAID,
        ConsultationPurchase.consumed_at.is_(None),
        ConsultationPurchase.credited_at.is_(None),
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
    _reflow_scheduled_passes(purchase.user_id)
    db.session.commit()
    from app.consultations.analytics import capture_consultation_event
    capture_consultation_event(
        'consultation_pass_refunded',
        user_id=purchase.user_id,
        insert_id=f'consultation_pass_refunded:{purchase.id}',
        durable=True,
    )
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
        _reflow_scheduled_passes(purchase.user_id)
        db.session.commit()
        from app.consultations.analytics import capture_consultation_event
        capture_consultation_event(
            'consultation_pass_refunded',
            user_id=purchase.user_id,
            insert_id=f'consultation_pass_refunded:{purchase.id}',
            durable=True,
        )
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

    A partial refund of an unused pass withdraws the whole pass: a part-refunded
    pass must not still take consultations live.
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
    _reflow_scheduled_passes(purchase.user_id)
    from app.consultations.analytics import capture_consultation_event
    capture_consultation_event(
        'consultation_pass_refunded',
        user_id=purchase.user_id,
        insert_id=f'consultation_pass_refunded:{purchase.id}',
        durable=True,
    )
    return True


def _record_closed_dispute(purchase: ConsultationPurchase, status: Optional[str]) -> bool:
    """Apply the outcome of a dispute. A win restores the pass for whatever is left of its window."""
    if status in _DISPUTE_MERCHANT_KEEPS:
        if purchase.status != ConsultationPurchase.STATUS_DISPUTED:
            return False
        purchase.status = ConsultationPurchase.STATUS_PAID
        return True
    if status == 'lost' and purchase.status != ConsultationPurchase.STATUS_REFUNDED:
        purchase.status = ConsultationPurchase.STATUS_REFUNDED
        purchase.refunded_at = purchase.refunded_at or utcnow_naive()
        _reflow_scheduled_passes(purchase.user_id)
        from app.consultations.analytics import capture_consultation_event
        capture_consultation_event(
            'consultation_pass_refunded',
            user_id=purchase.user_id,
            insert_id=f'consultation_pass_refunded:{purchase.id}',
            durable=True,
        )
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
