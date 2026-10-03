"""The host's side of a consultation: set-up, dashboard, moderation, report, account.

Every route is owner-only. Site admins have no access to a customer's
consultation through these routes.
"""
import csv
import io
from datetime import timedelta

import segno
from flask import (
    Response,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babel import format_date, gettext as _
from flask_login import current_user, login_required

from app import db, limiter
from app.consultations import billing, consultations_bp, emails, jobs, service, sharing
from app.consultations.drafting import statement_warnings
from app.consultations.forms import ActionForm, QuestionForm, SettingsForm, StartForm
from app.consultations.pdf import pdf_rendering_available, report_pdf
from app.consultations.report import (
    build_report_data,
    latest_report,
    live_board,
    report_csv_rows,
    report_view_context,
    statements_by_verdict,
)
from app.discussions.thresholds import RESULT_MIN_VOTES
from app.lib.time import utcnow_naive
from app.models import Consultation, ConsultationPurchase, ConsultationReport, Discussion

# The host's set-up steps, in order.
STEPS = ('question', 'statements', 'settings', 'go_live', 'share')


def _owned_or_404(consultation_id: int) -> Consultation:
    consultation = db.session.get(Consultation, consultation_id)
    if consultation is None or consultation.owner_user_id != current_user.id:
        abort(404)
    return consultation


def _no_index(response):
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


def _pounds(pence: int) -> str:
    pounds = pence / 100
    return f'£{pounds:,.0f}' if pounds == int(pounds) else f'£{pounds:,.2f}'


def _price(config_key: str) -> str:
    """A configured price in pence as ``£99`` or ``£99.50``."""
    return _pounds(current_app.config[config_key])


@consultations_bp.context_processor
def _prices():
    return {
        'price_single': _price('CONSULTATION_PRICE_SINGLE_PENCE'),
        'price_annual': _price('CONSULTATION_PRICE_ANNUAL_PENCE'),
        'trial_days': current_app.config.get('CONSULTATION_TRIAL_DAYS', 14),
    }


def _access_notice(user, closes_at=None) -> dict:
    """When this account's access ends, and whether a chosen close sits past it.

    Before the first go-live, the date is the trial end if they went live now.
    """
    end = billing.access_ends_at(user)
    starts_on_go_live = False
    if end is None and not getattr(user, 'is_admin', False) and billing.trial_available(user):
        end = utcnow_naive() + timedelta(days=current_app.config.get('CONSULTATION_TRIAL_DAYS', 14))
        starts_on_go_live = True
    return {
        'access_until': format_date(end, 'd MMMM y') if end else None,
        'access_ends_before_close': bool(end and closes_at and closes_at > end),
        'access_starts_on_go_live': starts_on_go_live,
    }


# ── The product page ────────────────────────────────────────────────────────

@consultations_bp.route('/consultations/self-serve')
def landing():
    has_consultations = current_user.is_authenticated and db.session.query(
        Consultation.query.filter_by(owner_user_id=current_user.id).exists()
    ).scalar()
    from app.consultations import example

    data = example.example_report_data()
    return render_template(
        'consultations/landing.html',
        has_consultations=bool(has_consultations),
        example_data=data,
        example_narrative=example.example_narrative(),
        example_groups=statements_by_verdict(data),
        example_highlights=example.example_highlights(),
        use_cases=example.use_case_examples(),
    )


# ── Getting in ──────────────────────────────────────────────────────────────

@consultations_bp.route('/consultations/start', methods=['GET', 'POST'])
@limiter.limit('60 per minute', methods=['GET'])
@limiter.limit('10 per hour', methods=['POST'])
def start():
    """Entry point from the marketing page. Signs a new host in by email alone."""
    if current_user.is_authenticated:
        return redirect(url_for('consultations.new'))

    form = StartForm()
    if not form.validate_on_submit():
        return render_template('consultations/start.html', form=form)

    from app.email_utils import extract_clean_email
    from app.lib.bot_protection import check_honeypot_only
    from app.lib.email_normalize import normalize_trial_email
    from app.lib.magic_login_dispatch import dispatch_magic_login_email
    from app.lib.passwordless_signup import create_passwordless_user
    from app.lib.trial_abuse import find_user_by_canonical_email, is_disposable_email

    email = extract_clean_email(form.email.data)
    if check_honeypot_only() or not email or is_disposable_email(email):
        flash(_('Please use a work email address we can send your sign-in link to.'), 'error')
        return render_template('consultations/start.html', form=form)

    user = find_user_by_canonical_email(email)
    if user is None:
        try:
            user = create_passwordless_user(normalize_trial_email(email))
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Could not create consultation host account')
            flash(_('Something went wrong. Please try again in a moment.'), 'error')
            return render_template('consultations/start.html', form=form)
        from app.consultations.analytics import capture_consultation_event
        capture_consultation_event(
            'consultation_signed_up',
            user_id=user.id,
            insert_id=f'consultation_signed_up:{user.id}',
            durable=True,
        )

    next_url = url_for('consultations.new')
    session['pending_post_auth_redirect'] = next_url
    sent = dispatch_magic_login_email(
        user,
        lambda token: url_for('auth.magic_link_landing', token=token, next=next_url, _external=True),
        submitted_email=email,
    )
    if not sent:
        flash(_('We could not send the sign-in email. Please try again in a moment.'), 'error')
        return render_template('consultations/start.html', form=form)
    return render_template('consultations/check_inbox.html', email=email)


@consultations_bp.route('/consultations/mine')
@login_required
def mine():
    consultations = (
        Consultation.query.filter_by(owner_user_id=current_user.id)
        .order_by(Consultation.created_at.desc())
        .all()
    )
    if not consultations:
        return redirect(url_for('consultations.new'))
    return render_template(
        'consultations/mine.html',
        consultations=[(c, service.participation(c) if not c.is_draft else None) for c in consultations],
        action_form=ActionForm(),
    )


# ── Step 1: the question ────────────────────────────────────────────────────

def _last_organisation_name() -> str:
    previous = (
        Consultation.query.filter_by(owner_user_id=current_user.id)
        .order_by(Consultation.id.desc())
        .first()
    )
    if previous:
        return previous.organisation_name
    profile = getattr(current_user, 'company_profile', None)
    return getattr(profile, 'company_name', '') or ''


@consultations_bp.route('/consultations/new', methods=['GET', 'POST'])
@login_required
@limiter.limit('30 per hour', methods=['POST'])
def new():
    form = QuestionForm()
    if request.method == 'GET':
        form.organisation_name.data = _last_organisation_name()
    if form.validate_on_submit():
        consultation = service.create_consultation(
            current_user,
            question=form.question.data,
            organisation_name=form.organisation_name.data,
            context=form.context.data,
            audience_label=form.audience_label.data,
            audience_size=form.audience_size.data,
        )
        from app.consultations.analytics import capture_consultation_event
        capture_consultation_event(
            'consultation_created',
            user_id=current_user.id,
            insert_id=f'consultation_created:{consultation.id}',
            properties={'consultation_id': consultation.id},
        )
        jobs.enqueue_drafting(consultation)
        return redirect(url_for('consultations.statements', consultation_id=consultation.id))
    return render_template('consultations/question.html', form=form, consultation=None, step='question')


@consultations_bp.route('/consultations/<int:consultation_id>/question', methods=['GET', 'POST'])
@login_required
def question(consultation_id):
    consultation = _owned_or_404(consultation_id)
    if not consultation.is_draft:
        return redirect(url_for('consultations.dashboard', consultation_id=consultation.id))
    form = QuestionForm(obj=consultation)
    if form.validate_on_submit():
        consultation.question = ' '.join(form.question.data.split())
        consultation.discussion.title = consultation.question[:200]
        consultation.organisation_name = ' '.join(form.organisation_name.data.split())
        consultation.audience_label = (form.audience_label.data or '').strip() or None
        consultation.audience_size = form.audience_size.data
        consultation.context = (form.context.data or '').strip() or None
        db.session.commit()
        return redirect(url_for('consultations.statements', consultation_id=consultation.id))
    return render_template('consultations/question.html', form=form, consultation=consultation, step='question')


# ── Step 2: the statements ──────────────────────────────────────────────────

def _statement_rows(consultation: Consultation) -> list:
    return [
        {'statement': s, 'warnings': statement_warnings(s.content)}
        for s in service.published_statements(consultation)
    ]


@consultations_bp.route('/consultations/<int:consultation_id>/statements')
@login_required
def statements(consultation_id):
    consultation = _owned_or_404(consultation_id)
    rows = _statement_rows(consultation)
    stances = {'pro': 0, 'con': 0, 'neutral': 0}
    for row in rows:
        stance = row['statement'].seed_stance
        if stance in stances:
            stances[stance] += 1
    return render_template(
        'consultations/statements.html',
        consultation=consultation,
        rows=rows,
        stances=stances,
        drafting=jobs.drafting_state(consultation),
        minimum=current_app.config.get('CONSULTATION_MIN_STATEMENTS', 5),
        maximum=current_app.config.get('CONSULTATION_MAX_STATEMENTS', 30),
        max_length=service.STATEMENT_MAX_LENGTH,
        action_form=ActionForm(),
        step='statements',
    )


@consultations_bp.route('/consultations/<int:consultation_id>/statements/status.json')
@login_required
def drafting_status(consultation_id):
    consultation = _owned_or_404(consultation_id)
    return jsonify(jobs.drafting_state(consultation))


def _back_to_statements(consultation: Consultation):
    if consultation.is_draft:
        return redirect(url_for('consultations.statements', consultation_id=consultation.id))
    return redirect(url_for('consultations.dashboard', consultation_id=consultation.id) + '#statements')


@consultations_bp.route('/consultations/<int:consultation_id>/statements/add', methods=['POST'])
@login_required
def add_statement(consultation_id):
    consultation = _owned_or_404(consultation_id)
    if consultation.is_closed:
        abort(409)
    try:
        service.add_statement(consultation, request.form.get('content', ''))
    except service.ConsultationError as exc:
        flash(str(exc), 'error')
    return _back_to_statements(consultation)


@consultations_bp.route('/consultations/<int:consultation_id>/statements/<int:statement_id>/edit', methods=['POST'])
@login_required
def edit_statement(consultation_id, statement_id):
    consultation = _owned_or_404(consultation_id)
    try:
        service.edit_statement(consultation, statement_id, request.form.get('content', ''))
    except service.ConsultationError as exc:
        flash(str(exc), 'error')
    return _back_to_statements(consultation)


@consultations_bp.route('/consultations/<int:consultation_id>/statements/<int:statement_id>/remove', methods=['POST'])
@login_required
def remove_statement(consultation_id, statement_id):
    consultation = _owned_or_404(consultation_id)
    try:
        service.remove_statement(consultation, statement_id)
        if not consultation.is_draft and not service.published_statements(consultation):
            flash(_(
                'That was the last statement. People with the link have nothing to answer until you add one.'
            ), 'error')
        elif not consultation.is_draft:
            flash(_('Statement withdrawn. Votes already cast on it are no longer counted.'), 'success')
    except service.ConsultationError as exc:
        flash(str(exc), 'error')
    return _back_to_statements(consultation)


@consultations_bp.route('/consultations/<int:consultation_id>/statements/draft', methods=['POST'])
@login_required
@limiter.limit('20 per hour')
def draft_more(consultation_id):
    consultation = _owned_or_404(consultation_id)
    if not consultation.is_draft:
        abort(409)
    job, _created = jobs.enqueue_drafting(consultation)
    if job is None:
        flash(_('You have reached today’s limit for AI drafting. You can still write statements yourself.'), 'warning')
    return _back_to_statements(consultation)


# ── Step 3: settings ────────────────────────────────────────────────────────

@consultations_bp.route('/consultations/<int:consultation_id>/settings', methods=['GET', 'POST'])
@login_required
def settings(consultation_id):
    consultation = _owned_or_404(consultation_id)
    if not consultation.is_draft:
        return redirect(url_for('consultations.dashboard', consultation_id=consultation.id))
    form = SettingsForm(obj=consultation)
    if request.method == 'GET':
        form.open_days.data = current_app.config.get('CONSULTATION_DEFAULT_OPEN_DAYS', 7)
        if consultation.closes_at:
            form.open_days.data = max(1, (consultation.closes_at - utcnow_naive()).days + 1)
    if form.validate_on_submit():
        consultation.allow_audience_statements = form.allow_audience_statements.data
        consultation.show_results_to_participants = form.show_results_to_participants.data
        service.set_closing_time(consultation, utcnow_naive() + timedelta(days=form.open_days.data))
        return redirect(url_for('consultations.go_live', consultation_id=consultation.id))
    return render_template(
        'consultations/settings.html',
        form=form,
        consultation=consultation,
        step='settings',
        result_min_votes=RESULT_MIN_VOTES,
        **_access_notice(current_user, consultation.closes_at),
    )


# ── Step 4: go live ─────────────────────────────────────────────────────────

@consultations_bp.route('/consultations/<int:consultation_id>/go-live', methods=['GET', 'POST'])
@login_required
def go_live(consultation_id):
    consultation = _owned_or_404(consultation_id)
    if not consultation.is_draft:
        return redirect(url_for('consultations.share', consultation_id=consultation.id))
    form = ActionForm()
    blocker = service.publish_blocker(consultation)
    covered_by = billing.entitlement(current_user)

    if form.validate_on_submit():
        if blocker:
            flash(blocker, 'error')
            return redirect(url_for('consultations.statements', consultation_id=consultation.id))
        if covered_by is None and not billing.trial_available(current_user):
            flash(_('Choose how you would like to pay to take this consultation live.'), 'info')
        else:
            return _take_live(consultation)

    current_pass = billing.active_pass(current_user) if covered_by == Consultation.COVERED_BY_PURCHASE else None
    trial = billing.active_trial(current_user)
    return render_template(
        'consultations/go_live.html',
        consultation=consultation,
        form=form,
        blocker=blocker,
        covered_by=covered_by,
        trial_offer=billing.trial_available(current_user),
        trial_until=format_date(trial.ends_at, 'd MMMM y') if trial else None,
        pass_until=format_date(current_pass.valid_until, 'd MMMM y') if current_pass and current_pass.valid_until else None,
        statement_count=len(service.published_statements(consultation)),
        open_days=max(1, (consultation.closes_at - utcnow_naive()).days + 1) if consultation.closes_at
        else current_app.config.get('CONSULTATION_DEFAULT_OPEN_DAYS', 7),
        step='go_live',
        **_access_notice(current_user, consultation.closes_at),
    )


def _take_live(consultation: Consultation):
    try:
        billing.go_live(consultation, current_user)
    except (billing.BillingError, service.ConsultationError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('consultations.go_live', consultation_id=consultation.id))
    try:
        emails.notify_live(consultation)
    except Exception:
        current_app.logger.exception('Could not send the live notice for consultation %s', consultation.id)
    flash(_('Your consultation is live.'), 'success')
    return redirect(url_for('consultations.share', consultation_id=consultation.id))


@consultations_bp.route('/consultations/checkout', methods=['POST'])
@login_required
@limiter.limit('20 per hour')
def checkout():
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    plan = request.form.get('plan')
    if plan not in ('annual', 'single'):
        abort(400)
    consultation_id = request.form.get('consultation_id', type=int)
    if consultation_id is not None:
        _owned_or_404(consultation_id)
    create = billing.create_annual_checkout if plan == 'annual' else billing.create_single_checkout
    try:
        checkout_session = create(current_user, consultation_id=consultation_id)
        session_id = getattr(checkout_session, 'id', None)
        if session_id is None and isinstance(checkout_session, dict):
            session_id = checkout_session.get('id')
        if session_id:
            from app.consultations.analytics import capture_consultation_event
            capture_consultation_event(
                'consultation_checkout_started',
                user_id=current_user.id,
                insert_id=f'consultation_checkout_started:{session_id}',
                properties={'plan': 'annual' if plan == 'annual' else 'single'},
            )
    except billing.BillingError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('consultations.account'))
    except Exception:
        current_app.logger.exception('Could not start consultation checkout')
        flash(_('We could not open the payment page. Nothing has been charged. Please try again.'), 'error')
        if consultation_id:
            return redirect(url_for('consultations.go_live', consultation_id=consultation_id))
        return redirect(url_for('consultations.account'))
    return redirect(checkout_session.url, code=303)


@consultations_bp.route('/consultations/checkout/success')
@login_required
def checkout_success():
    """Return from Stripe. Applies the payment now rather than waiting for the webhook."""
    from app.billing.service import _get_stripe_field, _get_stripe_metadata, _stripe_call, get_stripe

    session_id = request.args.get('session_id', '')
    if not session_id:
        return redirect(url_for('consultations.account'))
    try:
        checkout_session = _stripe_call(get_stripe().checkout.Session.retrieve, session_id)
    except Exception:
        current_app.logger.exception('Could not load consultation checkout %s', session_id)
        flash(_('Your payment is being confirmed. This page will update shortly.'), 'info')
        return redirect(url_for('consultations.account'))

    metadata = _get_stripe_metadata(checkout_session)
    if (
        str(metadata.get('user_id')) != str(current_user.id)
        or _get_stripe_field(checkout_session, 'customer') != current_user.stripe_customer_id
    ):
        abort(404)
    try:
        billing.fulfil_checkout_session(checkout_session)
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Could not apply consultation checkout %s', session_id)
        flash(_('Your payment is being confirmed. This page will update shortly.'), 'info')
        return redirect(url_for('consultations.account'))

    consultation_id = metadata.get('consultation_id')
    if consultation_id and str(consultation_id).isdigit():
        consultation = db.session.get(Consultation, int(consultation_id))
        if consultation and consultation.owner_user_id == current_user.id and consultation.is_draft:
            if billing.entitlement(current_user):
                return _take_live(consultation)
    flash(_('Thank you. Your payment has been received.'), 'success')
    return redirect(url_for('consultations.account'))


# ── Step 5: share ───────────────────────────────────────────────────────────

@consultations_bp.route('/consultations/<int:consultation_id>/share')
@login_required
def share(consultation_id):
    consultation = _owned_or_404(consultation_id)
    if consultation.is_draft:
        return redirect(url_for('consultations.go_live', consultation_id=consultation.id))
    participant_url = url_for('consultations.participate', token=consultation.access_token, _external=True)
    return render_template(
        'consultations/share.html',
        consultation=consultation,
        participant_url=participant_url,
        invitation_text=emails.invitation_text(consultation),
        reminder_text=emails.reminder_text(consultation),
        share_text=sharing.short_message(consultation),
        share_groups=sharing.share_groups(consultation, participant_url),
        action_form=ActionForm(),
        step='share',
    )


@consultations_bp.route('/consultations/<int:consultation_id>/qr.<fmt>')
@login_required
def qr_code(consultation_id, fmt):
    consultation = _owned_or_404(consultation_id)
    if fmt not in ('svg', 'png'):
        abort(404)
    link = url_for('consultations.participate', token=consultation.access_token, _external=True)
    code = segno.make(link, error='m')
    buffer = io.BytesIO()
    # A 4-module quiet zone is what scanners expect on a projected slide.
    code.save(buffer, kind=fmt, scale=12 if fmt == 'png' else 8, border=4, dark='#111827')
    response = Response(
        buffer.getvalue(),
        mimetype='image/svg+xml' if fmt == 'svg' else 'image/png',
    )
    response.headers['Cache-Control'] = 'private, no-store'
    if request.args.get('download'):
        response.headers['Content-Disposition'] = f'attachment; filename="consultation-qr.{fmt}"'
    return response


@consultations_bp.route('/consultations/<int:consultation_id>/present')
@login_required
def present(consultation_id):
    """The big-screen view: the code to join, then the results when the host reveals them."""
    consultation = _owned_or_404(consultation_id)
    if consultation.is_draft:
        return redirect(url_for('consultations.go_live', consultation_id=consultation.id))
    data = _live_results(consultation)
    board = live_board(data)
    context = {
        'consultation': consultation,
        'data': data,
        'groups': board['groups'],
        'board_counts': board['counts'],
        'provisional': board['provisional'],
        'result_min_votes': RESULT_MIN_VOTES,
    }
    if request.args.get('fragment'):
        # Only the results, re-fetched by the page while voting is open.
        response = Response(render_template('consultations/_present_results.html', **context))
    else:
        response = Response(render_template(
            'consultations/present.html',
            view='join' if consultation.is_live and request.args.get('view') != 'results' else 'results',
            participant_url=url_for('consultations.participate', token=consultation.access_token, _external=True),
            **context,
        ))
    response.headers['Cache-Control'] = 'private, no-store'
    return _no_index(response)


# ── Dashboard ───────────────────────────────────────────────────────────────

def _live_results(consultation: Consultation) -> dict:
    return build_report_data(
        consultation.discussion,
        question=consultation.question,
        organisation_name=consultation.organisation_name,
        audience_label=consultation.audience_label,
        audience_size=consultation.audience_size,
        opened_at=consultation.published_at,
        closed_at=consultation.closed_at,
    )


@consultations_bp.route('/consultations/<int:consultation_id>')
@login_required
def dashboard(consultation_id):
    consultation = _owned_or_404(consultation_id)
    if consultation.is_draft:
        return redirect(url_for('consultations.statements', consultation_id=consultation.id))
    data = _live_results(consultation)
    return render_template(
        'consultations/dashboard.html',
        consultation=consultation,
        data=data,
        groups=statements_by_verdict(data),
        result_min_votes=RESULT_MIN_VOTES,
        pending_count=len(service.pending_statements(consultation)),
        report=latest_report(consultation, kind=ConsultationReport.KIND_FINAL),
        report_state=jobs.report_state(consultation),
        participant_url=url_for('consultations.participate', token=consultation.access_token, _external=True),
        reminder_text=emails.reminder_text(consultation),
        max_length=service.STATEMENT_MAX_LENGTH,
        action_form=ActionForm(),
        now=utcnow_naive(),
        closes_on=format_date(consultation.closes_at, 'd MMMM') if consultation.closes_at else '',
        closed_on=format_date(consultation.closed_at, 'd MMMM y') if consultation.closed_at else '',
        **_access_notice(current_user, consultation.closes_at),
    )


@consultations_bp.route('/consultations/<int:consultation_id>/status.json')
@login_required
def status(consultation_id):
    consultation = _owned_or_404(consultation_id)
    counts = service.participation(consultation)
    return jsonify({
        'status': consultation.status,
        'participants': counts['participants'],
        'votes': counts['votes'],
        'pending': len(service.pending_statements(consultation)),
        'report': jobs.report_state(consultation),
        'has_report': latest_report(consultation, kind=ConsultationReport.KIND_FINAL) is not None,
    })


@consultations_bp.route('/consultations/<int:consultation_id>/close', methods=['POST'])
@login_required
def close(consultation_id):
    consultation = _owned_or_404(consultation_id)
    if ActionForm().validate_on_submit() and consultation.is_live:
        jobs.close_and_report(consultation)
        flash(_('Voting has closed. Your report is being built.'), 'success')
        return redirect(url_for('consultations.report', consultation_id=consultation.id))
    return redirect(url_for('consultations.dashboard', consultation_id=consultation.id))


@consultations_bp.route('/consultations/<int:consultation_id>/extend', methods=['POST'])
@login_required
def extend(consultation_id):
    consultation = _owned_or_404(consultation_id)
    days = request.form.get('days', type=int)
    if consultation.is_draft or not days or not 1 <= days <= 90:
        abort(400)
    if not billing.may_keep_open(consultation, current_user):
        flash(_(
            'Your access has ended, so this consultation cannot stay open. '
            'Continue for %(single)s for 30 days or %(annual)s a year.',
            single=_price('CONSULTATION_PRICE_SINGLE_PENCE'), annual=_price('CONSULTATION_PRICE_ANNUAL_PENCE'),
        ), 'error')
        return redirect(url_for('consultations.account'))
    base = max(consultation.closes_at or utcnow_naive(), utcnow_naive())
    try:
        service.set_closing_time(consultation, base + timedelta(days=days))
        if billing.mark_passes_in_use(current_user):
            db.session.commit()
        end = billing.access_ends_at(current_user)
        if end is not None and consultation.closes_at and consultation.closes_at > end:
            flash(_(
                'The closing date is later than your access, which ends on %(date)s. '
                'Voting closes then and the report is built, unless you pay to continue.',
                date=format_date(end, 'd MMMM y'),
            ), 'info')
        else:
            flash(_('The consultation is open for longer. People can keep taking part.'), 'success')
    except service.ConsultationError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('consultations.dashboard', consultation_id=consultation.id))


@consultations_bp.route('/consultations/<int:consultation_id>/rotate-link', methods=['POST'])
@login_required
def rotate_link(consultation_id):
    consultation = _owned_or_404(consultation_id)
    if ActionForm().validate_on_submit():
        consultation.rotate_access_token()
        db.session.commit()
        flash(_('New link created. The old link and QR code no longer work.'), 'success')
    return redirect(url_for('consultations.share', consultation_id=consultation.id))


@consultations_bp.route('/consultations/<int:consultation_id>/delete', methods=['POST'])
@login_required
def delete(consultation_id):
    consultation = _owned_or_404(consultation_id)
    if ActionForm().validate_on_submit():
        service.delete_consultation(consultation)
        flash(_('Consultation deleted, with its statements, votes and reports.'), 'success')
    return redirect(url_for('consultations.mine'))


# ── Audience suggestions ────────────────────────────────────────────────────

@consultations_bp.route('/consultations/<int:consultation_id>/moderation')
@login_required
def moderation(consultation_id):
    consultation = _owned_or_404(consultation_id)
    return render_template(
        'consultations/moderation.html',
        consultation=consultation,
        pending=service.pending_statements(consultation),
        notes=jobs.screening_notes(consultation),
        action_form=ActionForm(),
    )


@consultations_bp.route(
    '/consultations/<int:consultation_id>/moderation/<int:statement_id>/<decision>', methods=['POST'],
)
@login_required
def moderate(consultation_id, statement_id, decision):
    consultation = _owned_or_404(consultation_id)
    if decision not in ('approve', 'reject') or not ActionForm().validate_on_submit():
        abort(400)
    try:
        if decision == 'approve':
            service.approve_statement(consultation, statement_id)
        else:
            service.reject_statement(consultation, statement_id)
    except service.ConsultationError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('consultations.moderation', consultation_id=consultation.id))


# ── Report ──────────────────────────────────────────────────────────────────

def _current_report(consultation: Consultation):
    """The newest report. After a reopen that is the interim one, not the
    final report from before voting reopened."""
    return latest_report(consultation)


def _shared_reports(consultation: Consultation) -> list:
    """Every report of this consultation that a link still opens, newest first."""
    return (
        ConsultationReport.query.filter(
            ConsultationReport.consultation_id == consultation.id,
            ConsultationReport.share_token.isnot(None),
        )
        .order_by(ConsultationReport.id.desc())
        .all()
    )


def _report_context(report: ConsultationReport) -> dict:
    return {'report': report, **report_view_context(
        report.data, report.narrative, report.narrative_source,
        is_interim=report.kind == ConsultationReport.KIND_INTERIM,
    )}


@consultations_bp.route('/consultations/<int:consultation_id>/report')
@login_required
def report(consultation_id):
    consultation = _owned_or_404(consultation_id)
    if consultation.is_draft:
        return redirect(url_for('consultations.statements', consultation_id=consultation.id))
    current = _current_report(consultation)
    state = jobs.report_state(consultation)
    if current is None:
        return render_template(
            'consultations/report_pending.html',
            consultation=consultation, report_state=state, action_form=ActionForm(),
        )
    return render_template(
        'consultations/report.html',
        consultation=consultation,
        report_state=state,
        pdf_available=pdf_rendering_available(),
        share_url=url_for('consultations.shared_report', share_token=current.share_token, _external=True)
        if current.is_shared else None,
        # A link the host made for an earlier report still opens that report.
        earlier_share=next((r for r in _shared_reports(consultation) if r.id != current.id), None),
        action_form=ActionForm(),
        **_report_context(current),
    )


@consultations_bp.route('/consultations/<int:consultation_id>/report/build', methods=['POST'])
@login_required
@limiter.limit('12 per hour')
def build_report(consultation_id):
    """Build a report now: interim while voting is open, final once closed."""
    consultation = _owned_or_404(consultation_id)
    if consultation.is_draft or not ActionForm().validate_on_submit():
        abort(400)
    kind = ConsultationReport.KIND_FINAL if consultation.is_closed else ConsultationReport.KIND_INTERIM
    jobs.enqueue_report(consultation, kind=kind)
    return redirect(url_for('consultations.report', consultation_id=consultation.id))


@consultations_bp.route('/consultations/<int:consultation_id>/report/<action>', methods=['POST'])
@login_required
def share_report(consultation_id, action):
    consultation = _owned_or_404(consultation_id)
    current = _current_report(consultation)
    if current is None or action not in ('share', 'unshare') or not ActionForm().validate_on_submit():
        abort(400)
    shared = _shared_reports(consultation)
    if action == 'share':
        if not current.is_shared:
            # One link per consultation: a link already given out for an
            # earlier report now opens this one.
            token = shared[0].share_token if shared else None
            for earlier in shared:
                earlier.unshare()
            db.session.flush()
            current.share(token)
        flash(_('Anyone with the link can now read this report.'), 'success')
    else:
        for report_row in shared:
            report_row.unshare()
        flash(_('The report link no longer works. Only you can see the report.'), 'success')
    db.session.commit()
    return redirect(url_for('consultations.report', consultation_id=consultation.id))


def _pdf_response(report: ConsultationReport):
    pdf = report_pdf(report)
    if pdf is None:
        abort(404)
    response = Response(pdf, mimetype='application/pdf')
    response.headers['Content-Disposition'] = 'attachment; filename="consultation-report.pdf"'
    response.headers['Cache-Control'] = 'private, no-store'
    return _no_index(response)


@consultations_bp.route('/consultations/<int:consultation_id>/report.pdf')
@login_required
def report_pdf_download(consultation_id):
    consultation = _owned_or_404(consultation_id)
    current = _current_report(consultation)
    if current is None:
        abort(404)
    return _pdf_response(current)


@consultations_bp.route('/consultations/<int:consultation_id>/results.csv')
@login_required
def results_csv(consultation_id):
    consultation = _owned_or_404(consultation_id)
    current = _current_report(consultation)
    data = current.data if current else _live_results(consultation)
    from app.lib.csv_safety import excel_safe_text

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in report_csv_rows(data):
        writer.writerow([excel_safe_text(cell) if isinstance(cell, str) else cell for cell in row])
    response = Response('﻿' + buffer.getvalue(), mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = 'attachment; filename="consultation-results.csv"'
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@consultations_bp.route('/r/<share_token>')
@limiter.limit('120 per minute')
def shared_report(share_token):
    """A report the host chose to share. The token is the only way in."""
    current = ConsultationReport.query.filter_by(share_token=share_token).first_or_404()
    response = _no_index(Response(render_template(
        'consultations/report_shared.html',
        pdf_available=pdf_rendering_available(),
        **_report_context(current),
    )))
    # The address is the key to the report: never pass it on as a referrer.
    g.referrer_policy = 'no-referrer'
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@consultations_bp.route('/r/<share_token>/report.pdf')
@limiter.limit('30 per minute')
def shared_report_pdf(share_token):
    current = ConsultationReport.query.filter_by(share_token=share_token).first_or_404()
    return _pdf_response(current)


@consultations_bp.route('/consultations/example-report')
def example_report():
    """The example report on the product page.

    Built from a real public discussion when one is configured, otherwise from
    the worked example in ``example.py``. Either way the page says which.
    """
    from app.consultations import example
    from app.consultations.narrative import template_narrative

    discussion_id = current_app.config.get('CONSULTATION_EXAMPLE_DISCUSSION_ID')
    discussion = db.session.get(Discussion, discussion_id) if discussion_id else None
    if discussion is not None and discussion.is_publicly_listable:
        data = build_report_data(
            discussion,
            question=discussion.title,
            organisation_name='Society Speaks',
            audience_label=_('People who took part in this public discussion on Society Speaks'),
            opened_at=discussion.created_at,
        )
        context = report_view_context(data, template_narrative(data), ConsultationReport.NARRATIVE_TEMPLATE)
        illustration = False
    else:
        context = report_view_context(
            example.example_report_data(), example.example_narrative(), example.NARRATIVE_EXAMPLE,
        )
        illustration = True
    return render_template('consultations/report_example.html', illustration=illustration, **context)


# ── Account ─────────────────────────────────────────────────────────────────

@consultations_bp.route('/consultations/account')
@login_required
def account():
    purchases = (
        ConsultationPurchase.query.filter_by(user_id=current_user.id)
        .order_by(ConsultationPurchase.id.desc())
        .all()
    )
    credit_pence, _passes = billing.uncredited_pass_credit(current_user)
    return render_template(
        'consultations/account.html',
        plan=billing.active_plan(current_user),
        trial=billing.active_trial(current_user),
        can_buy_pass=billing.pass_purchase_blocker(current_user) is None,
        pass_credit=_pounds(credit_pence) if credit_pence else None,
        purchases=purchases,
        has_billing_history=bool(current_user.stripe_customer_id),
        action_form=ActionForm(),
    )


@consultations_bp.route('/consultations/account/billing', methods=['POST'])
@login_required
def billing_portal():
    if not ActionForm().validate_on_submit():
        abort(400)
    try:
        portal = billing.create_portal_session(current_user)
    except billing.BillingError as exc:
        flash(str(exc), 'info')
        return redirect(url_for('consultations.account'))
    except Exception:
        current_app.logger.exception('Could not open the billing portal')
        flash(_('We could not open the billing page. Please try again.'), 'error')
        return redirect(url_for('consultations.account'))
    return redirect(portal.url, code=303)


@consultations_bp.route('/consultations/purchases/<int:purchase_id>/refund', methods=['POST'])
@login_required
@limiter.limit('10 per hour')
def refund(purchase_id):
    if not ActionForm().validate_on_submit():
        abort(400)
    try:
        billing.refund_purchase(current_user, purchase_id)
        flash(_('Refunded. The money will be back on your card within 5 to 10 days.'), 'success')
    except billing.BillingError as exc:
        flash(str(exc), 'error')
    except Exception:
        current_app.logger.exception('Refund failed for purchase %s', purchase_id)
        flash(_('We could not refund that automatically. Nothing has changed. Please try again.'), 'error')
    return redirect(url_for('consultations.account'))
