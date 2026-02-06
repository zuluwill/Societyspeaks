"""
Partner Hub Routes

Routes for the partner-facing pages:
- /for-publishers - Partner hub landing page
- /for-publishers/embed - Embed code generator
- /for-publishers/api - API documentation
- /for-publishers/api-playground - Interactive API (Swagger UI)
- /for-publishers/openapi.yaml - OpenAPI 3.0 spec
- /for-publishers/rules - Rules of the Record
"""
import os
import re
import secrets
from functools import wraps
from datetime import datetime, timedelta
from urllib.parse import urlparse
from flask import render_template, request, current_app, send_from_directory, redirect, url_for, flash, session, Response
from app import db, limiter
from app.partner import partner_bp
from app.partner.constants import EMBED_THEMES, EMBED_ALLOWED_FONTS
from app.partner.keys import generate_partner_api_key, KEY_PREFIXES
from app.lib.auth_utils import (
    normalize_email,
    validate_email_format,
    validate_password,
    PARTNER_SIGNUP_RATE_LIMIT,
    PARTNER_LOGIN_RATE_LIMIT,
)
from app.models import Partner, PartnerDomain, PartnerApiKey, PartnerUsageEvent, generate_slug
from app.billing.service import create_partner_checkout_session, create_partner_portal_session, get_stripe


@partner_bp.route('/')
def hub():
    """
    Partner hub landing page.

    Explains Society Speaks as the public reasoning layer, the three primitives
    (Judgment Prompt, Audience Snapshot, Understanding Link), and provides
    links to the embed generator and API documentation.
    """
    return render_template(
        'partner/hub.html',
        base_url=_get_base_url(),
        demo_discussion_id=current_app.config.get('DEMO_DISCUSSION_ID')
    )


@partner_bp.route('/embed')
def embed_generator():
    """
    Embed code generator.

    Partners can enter an article URL or discussion ID, pick a theme,
    and get a ready-to-paste iframe snippet.
    """
    return render_template(
        'partner/embed_generator.html',
        themes=EMBED_THEMES,
        fonts=EMBED_ALLOWED_FONTS,
        base_url=_get_base_url()
    )


@partner_bp.route('/api')
def api_docs():
    """
    API documentation page.

    Documents the lookup API, snapshot API, and embed URL parameters.
    """
    return render_template('partner/api_docs.html', base_url=_get_base_url())


@partner_bp.route('/rules')
def rules_of_record():
    """
    Rules of the Record page.

    Plain English explanation of what partners may and may not do.
    """
    return render_template('partner/rules.html')


@partner_bp.route('/openapi.yaml')
def openapi_spec():
    """Serve the OpenAPI 3.0 spec for the Partner API (for Swagger UI and tooling)."""
    return send_from_directory(
        os.path.join(os.path.dirname(__file__)),
        'openapi.yaml',
        mimetype='application/x-yaml',
        as_attachment=False
    )


@partner_bp.route('/api-playground')
def api_playground():
    """
    Interactive API playground (Swagger UI).

    Partners can try lookup, snapshot, and oEmbed from the browser.
    Create Discussion requires an API key in the X-API-Key header.
    """
    return render_template('partner/api_playground.html')


_DOMAIN_RE = re.compile(r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$')


def _normalize_domain(raw_domain):
    """Normalize and validate a domain string. Returns None if empty or invalid."""
    if not raw_domain:
        return None
    domain = raw_domain.strip().lower()
    if domain.startswith('http://') or domain.startswith('https://'):
        parsed = urlparse(domain)
        domain = parsed.netloc
    domain = domain.split('/')[0].split(':')[0]  # strip path and port
    if not domain or len(domain) > 253:
        return None
    if not _DOMAIN_RE.match(domain):
        return None
    return domain


def _current_partner():
    """Return the current logged-in partner, or None if not logged in or account is inactive."""
    partner_id = session.get('partner_portal_id')
    if not partner_id:
        return None
    partner = Partner.query.get(partner_id)
    if not partner or partner.status != 'active':
        # Clear stale session for deactivated/deleted partners
        _clear_partner_session()
        return None
    return partner


def _build_partner_portal_context(partner):
    domains = partner.domains.order_by(PartnerDomain.created_at.desc()).all()
    keys = partner.api_keys.order_by(PartnerApiKey.created_at.desc()).all()
    has_verified_test_domain = any(d.env == 'test' and d.is_verified() for d in domains)
    has_test_key = any(k.env == 'test' and k.status == 'active' for k in keys)
    has_live_key = any(k.env == 'live' and k.status == 'active' for k in keys)
    return domains, keys, has_verified_test_domain, has_test_key, has_live_key


def _clear_partner_session():
    """Remove all partner-related keys from the session."""
    for key in list(session.keys()):
        if key.startswith('partner_'):
            session.pop(key, None)


def partner_login_required(f):
    """Decorator that ensures the user is logged in to the partner portal."""
    @wraps(f)
    def decorated(*args, **kwargs):
        partner = _current_partner()
        if not partner:
            flash('Please sign in to the Partner Portal.', 'warning')
            return redirect(url_for('partner.portal_login'))
        return f(*args, **kwargs)
    return decorated


def _get_base_url():
    """Return the configured base URL (DRY helper used by public + portal routes)."""
    return current_app.config.get('BASE_URL', 'https://societyspeaks.io')


def _validate_env(raw_env):
    """Normalize and validate an env parameter. Returns 'test' or 'live'."""
    return raw_env if raw_env in ('test', 'live') else 'test'


def _create_api_key_for_partner(partner, env):
    """Generate an API key, persist it, and return the full plaintext key."""
    full_key, key_hash, key_last4 = generate_partner_api_key(env)
    db.session.add(PartnerApiKey(
        partner_id=partner.id,
        key_prefix=KEY_PREFIXES[env],
        key_hash=key_hash,
        key_last4=key_last4,
        env=env
    ))
    return full_key


def _verify_dns_txt(domain, token):
    expected = f"societyspeaks-verify={token}"
    details = {
        'expected': expected,
        'records': [],
        'error': None
    }
    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, 'TXT')
        for rdata in answers:
            try:
                txt = ''.join([s.decode('utf-8') for s in rdata.strings])
            except Exception:
                txt = rdata.to_text().strip('"')
            details['records'].append(txt)
            if expected in txt:
                return True, details
    except Exception as exc:
        details['error'] = str(exc)
        return False, details
    return False, details


@partner_bp.route('/portal')
def portal_home():
    if _current_partner():
        return redirect(url_for('partner.portal_dashboard'))
    return redirect(url_for('partner.portal_login'))


@partner_bp.route('/portal/signup', methods=['GET', 'POST'])
@limiter.limit(PARTNER_SIGNUP_RATE_LIMIT)
def portal_signup():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = normalize_email(request.form.get('email'))
        password = request.form.get('password', '')
        domain = _normalize_domain(request.form.get('domain', ''))

        if not name or not email or not password:
            flash('Name, email, and password are required.', 'danger')
            return render_template('partner/portal/signup.html')

        email_ok, email_err = validate_email_format(email)
        if not email_ok:
            flash(email_err, 'danger')
            return render_template('partner/portal/signup.html')

        is_valid, error_message = validate_password(password)
        if not is_valid:
            flash(error_message, 'danger')
            return render_template('partner/portal/signup.html')

        if Partner.query.filter_by(contact_email=email).first():
            flash('An account with this email already exists. Please sign in.', 'warning')
            return redirect(url_for('partner.portal_login'))

        slug_base = generate_slug(name) or generate_slug(email.split('@')[0]) or 'partner'
        slug = slug_base
        counter = 1
        while Partner.query.filter_by(slug=slug).first():
            counter += 1
            slug = f"{slug_base}-{counter}"
            if counter > 100:
                flash('Could not generate a unique account identifier. Please try a different name.', 'danger')
                return render_template('partner/portal/signup.html')

        try:
            partner = Partner(
                name=name[:200],  # enforce model max length
                slug=slug,
                contact_email=email,
                status='active',
                billing_status='inactive'
            )
            partner.set_password(password)
            db.session.add(partner)
            db.session.flush()

            if domain:
                token = secrets.token_hex(16)
                db.session.add(PartnerDomain(
                    partner_id=partner.id,
                    domain=domain,
                    env='test',
                    verification_method='dns_txt',
                    verification_token=token
                ))

            full_key = _create_api_key_for_partner(partner, 'test')
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to create partner account")
            flash('An error occurred creating your account. Please try again.', 'danger')
            return render_template('partner/portal/signup.html')

        session['partner_portal_id'] = partner.id
        session['partner_new_key'] = full_key
        flash('Your Partner Portal is ready. Your test key is shown once below.', 'success')
        return redirect(url_for('partner.portal_dashboard'))

    return render_template('partner/portal/signup.html')


@partner_bp.route('/portal/login', methods=['GET', 'POST'])
@limiter.limit(PARTNER_LOGIN_RATE_LIMIT)
def portal_login():
    if request.method == 'POST':
        email = normalize_email(request.form.get('email'))
        password = request.form.get('password', '')

        partner = Partner.query.filter_by(contact_email=email).first()

        # Temporary lockout after repeated failures (stored in session to keep it simple)
        # Uses '_lockout_' prefix (not 'partner_') so _clear_partner_session() won't wipe it
        lockout_key = f'_lockout_partner:{email}'
        fail_count = session.get(lockout_key, 0)
        lockout_until = session.get(f'{lockout_key}:until')

        if lockout_until:
            lockout_dt = datetime.fromisoformat(lockout_until)
            if datetime.utcnow() < lockout_dt:
                remaining = int((lockout_dt - datetime.utcnow()).total_seconds())
                flash(f'Too many failed attempts. Please try again in {remaining} seconds.', 'danger')
                return render_template('partner/portal/login.html')
            else:
                # Lockout expired, reset
                session.pop(lockout_key, None)
                session.pop(f'{lockout_key}:until', None)
                fail_count = 0

        if not partner or not partner.check_password(password):
            fail_count += 1
            session[lockout_key] = fail_count
            if fail_count >= 5:
                # Lock out for 5 minutes after 5 failures
                lockout_dt = datetime.utcnow() + timedelta(minutes=5)
                session[f'{lockout_key}:until'] = lockout_dt.isoformat()
                current_app.logger.warning(f"Partner login lockout triggered for {email} after {fail_count} failures")
                flash('Too many failed attempts. Please try again in 5 minutes.', 'danger')
            else:
                flash('Invalid email or password.', 'danger')
            return render_template('partner/portal/login.html')

        if partner.status != 'active':
            flash('This account has been deactivated. Please contact support.', 'danger')
            return render_template('partner/portal/login.html')

        # Successful login - clear failure tracking
        session.pop(lockout_key, None)
        session.pop(f'{lockout_key}:until', None)

        session['partner_portal_id'] = partner.id
        flash('Welcome back.', 'success')
        return redirect(url_for('partner.portal_dashboard'))

    return render_template('partner/portal/login.html')


@partner_bp.route('/portal/forgot-password', methods=['GET', 'POST'])
@limiter.limit("5 per 15 minutes")
def portal_forgot_password():
    """Send a password-reset email to the partner's contact email."""
    if request.method == 'POST':
        email = normalize_email(request.form.get('email'))
        # Always show the same message to avoid email enumeration
        generic_msg = 'If an account with that email exists, you will receive a reset link shortly.'

        partner = Partner.query.filter_by(contact_email=email).first()
        if partner and partner.status == 'active':
            token = partner.get_reset_token()
            reset_url = url_for('partner.portal_reset_password', token=token, _external=True)
            try:
                _send_partner_reset_email(partner, reset_url)
            except Exception:
                current_app.logger.exception(f"Failed to send partner password reset email to {email}")

        flash(generic_msg, 'info')
        return redirect(url_for('partner.portal_login'))

    return render_template('partner/portal/forgot_password.html')


@partner_bp.route('/portal/reset-password/<token>', methods=['GET', 'POST'])
def portal_reset_password(token):
    """Reset a partner's password using a valid token."""
    partner = Partner.verify_reset_token(token)
    if not partner:
        flash('This reset link is invalid or has expired. Please request a new one.', 'danger')
        return redirect(url_for('partner.portal_forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        is_valid, error_message = validate_password(password)
        if not is_valid:
            flash(error_message, 'danger')
            return render_template('partner/portal/reset_password.html', token=token)

        partner.set_password(password)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to reset partner password")
            flash('An error occurred. Please try again.', 'danger')
            return render_template('partner/portal/reset_password.html', token=token)

        session['partner_portal_id'] = partner.id
        flash('Your password has been reset. You are now signed in.', 'success')
        return redirect(url_for('partner.portal_dashboard'))

    return render_template('partner/portal/reset_password.html', token=token)


def _send_partner_reset_email(partner, reset_url):
    """Send a password-reset email via the existing Resend infrastructure."""
    from app.resend_client import get_resend_client
    client = get_resend_client()
    email_data = {
        'from': f"Society Speaks <noreply@{current_app.config.get('RESEND_DOMAIN', 'societyspeaks.io')}>",
        'to': [partner.contact_email],
        'subject': 'Reset your Society Speaks Partner Portal password',
        'html': render_template('emails/partner_password_reset.html',
                                partner=partner, reset_url=reset_url),
    }
    return client._send_with_retry(email_data)


@partner_bp.route('/portal/logout')
def portal_logout():
    _clear_partner_session()
    flash('Signed out.', 'success')
    return redirect(url_for('partner.portal_login'))


@partner_bp.route('/portal/dashboard')
@partner_login_required
def portal_dashboard():
    from sqlalchemy import func

    partner = _current_partner()
    domains, keys, has_verified_test_domain, has_test_key, has_live_key = _build_partner_portal_context(partner)
    new_key = session.pop('partner_new_key', None)
    dns_checks = session.get('partner_dns_checks', {})

    since = datetime.utcnow() - timedelta(days=30)
    usage_rows = PartnerUsageEvent.query.filter(
        PartnerUsageEvent.partner_id == partner.id,
        PartnerUsageEvent.created_at >= since
    ).with_entities(
        PartnerUsageEvent.event_type,
        func.sum(PartnerUsageEvent.quantity)
    ).group_by(PartnerUsageEvent.event_type).all()
    usage = {row[0]: int(row[1] or 0) for row in usage_rows}

    daily_since = datetime.utcnow() - timedelta(days=13)
    daily_rows = PartnerUsageEvent.query.filter(
        PartnerUsageEvent.partner_id == partner.id,
        PartnerUsageEvent.created_at >= daily_since
    ).with_entities(
        func.date(PartnerUsageEvent.created_at).label('day'),
        func.sum(PartnerUsageEvent.quantity)
    ).group_by('day').all()
    daily_map = {str(row[0]): int(row[1] or 0) for row in daily_rows}
    today = datetime.utcnow().date()
    usage_daily = []
    for idx in range(13, -1, -1):
        day = today - timedelta(days=idx)
        count = daily_map.get(day.isoformat(), 0)
        usage_daily.append({'label': day.strftime('%b %d'), 'count': count})
    usage_max = max([d['count'] for d in usage_daily] or [0])
    return render_template(
        'partner/portal/dashboard.html',
        partner=partner,
        domains=domains,
        keys=keys,
        new_key=new_key,
        has_verified_test_domain=has_verified_test_domain,
        has_test_key=has_test_key,
        has_live_key=has_live_key,
        usage=usage,
        usage_daily=usage_daily,
        usage_max=usage_max,
        dns_checks=dns_checks,
        base_url=_get_base_url()
    )


@partner_bp.route('/portal/getting-started')
@partner_login_required
def portal_getting_started():
    partner = _current_partner()
    domains, keys, has_verified_test_domain, has_test_key, has_live_key = _build_partner_portal_context(partner)
    return render_template(
        'partner/portal/getting_started.html',
        partner=partner,
        domains=domains,
        keys=keys,
        has_verified_test_domain=has_verified_test_domain,
        has_test_key=has_test_key,
        has_live_key=has_live_key,
        base_url=_get_base_url()
    )


@partner_bp.route('/portal/getting-started/success')
@partner_login_required
def portal_getting_started_success():
    partner = _current_partner()
    domains, keys, has_verified_test_domain, has_test_key, has_live_key = _build_partner_portal_context(partner)
    return render_template(
        'partner/portal/success.html',
        partner=partner,
        domains=domains,
        keys=keys,
        has_verified_test_domain=has_verified_test_domain,
        has_test_key=has_test_key,
        has_live_key=has_live_key,
        base_url=_get_base_url()
    )


@partner_bp.route('/portal/usage.csv')
@limiter.limit("10 per minute")
@partner_login_required
def portal_usage_csv():
    from sqlalchemy import func
    import csv
    from io import StringIO

    partner = _current_partner()
    since = datetime.utcnow() - timedelta(days=90)
    rows = PartnerUsageEvent.query.filter(
        PartnerUsageEvent.partner_id == partner.id,
        PartnerUsageEvent.created_at >= since
    ).with_entities(
        func.date(PartnerUsageEvent.created_at).label('day'),
        PartnerUsageEvent.event_type,
        func.sum(PartnerUsageEvent.quantity)
    ).group_by('day', PartnerUsageEvent.event_type).order_by('day').all()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['date', 'event_type', 'quantity'])
    for row in rows:
        writer.writerow([str(row[0]), row[1], int(row[2] or 0)])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=partner_usage.csv'}
    )


@partner_bp.route('/portal/domains/add', methods=['POST'])
@partner_login_required
def portal_add_domain():
    partner = _current_partner()
    domain = _normalize_domain(request.form.get('domain', ''))
    env = _validate_env(request.form.get('env', 'test'))
    if not domain:
        flash('Please enter a valid domain.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    if PartnerDomain.query.filter_by(partner_id=partner.id, domain=domain, env=env).first():
        flash('That domain already exists.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))

    # Prevent another partner from claiming a domain already verified elsewhere
    existing_verified = PartnerDomain.query.filter(
        PartnerDomain.domain == domain,
        PartnerDomain.partner_id != partner.id,
        PartnerDomain.verified_at.isnot(None)
    ).first()
    if existing_verified:
        flash('This domain is already verified by another partner.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    token = secrets.token_hex(16)
    db.session.add(PartnerDomain(
        partner_id=partner.id,
        domain=domain,
        env=env,
        verification_method='dns_txt',
        verification_token=token
    ))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to add partner domain")
        flash('An error occurred adding the domain. Please try again.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))
    flash('Domain added. Verify DNS to activate.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/domains/<int:domain_id>/verify', methods=['POST'])
@partner_login_required
def portal_verify_domain(domain_id):
    partner = _current_partner()
    domain = PartnerDomain.query.filter_by(id=domain_id, partner_id=partner.id).first_or_404()
    if domain.is_verified():
        flash('Domain already verified.', 'info')
        return redirect(url_for('partner.portal_dashboard'))

    # Cooldown: at most one verification attempt per domain every 30 seconds
    dns_checks = session.get('partner_dns_checks', {})
    prev_check = dns_checks.get(str(domain.id))
    if prev_check and prev_check.get('checked_at'):
        try:
            prev_dt = datetime.fromisoformat(prev_check['checked_at'])
            cooldown_seconds = 30
            if (datetime.utcnow() - prev_dt).total_seconds() < cooldown_seconds:
                flash('Please wait 30 seconds between verification attempts.', 'warning')
                return redirect(url_for('partner.portal_dashboard'))
        except (ValueError, TypeError):
            pass  # Malformed date in session, allow the check

    verified, details = _verify_dns_txt(domain.domain, domain.verification_token)
    dns_checks[str(domain.id)] = {
        'checked_at': datetime.utcnow().isoformat(),
        'expected': details.get('expected'),
        'records': details.get('records', [])[:3],
        'error': details.get('error'),
        'verified': verified
    }
    # Keep only the 10 most recent checks to avoid session bloat
    if len(dns_checks) > 10:
        sorted_keys = sorted(dns_checks, key=lambda k: dns_checks[k].get('checked_at', ''))
        for old_key in sorted_keys[:-10]:
            del dns_checks[old_key]
    session['partner_dns_checks'] = dns_checks
    session.modified = True

    if verified:
        domain.verified_at = datetime.utcnow()
        db.session.commit()
        flash('Domain verified successfully.', 'success')
    else:
        if details.get('error'):
            flash('Verification failed. DNS lookup error; check your DNS provider and try again.', 'danger')
        else:
            flash('Verification failed. TXT record not found yet. Check the expected value and try again.', 'danger')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/keys/create', methods=['POST'])
@partner_login_required
def portal_create_key():
    partner = _current_partner()
    env = _validate_env(request.form.get('env', 'test'))

    if env == 'live' and partner.billing_status != 'active':
        flash('Live keys require an active subscription.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))

    active_key_count = PartnerApiKey.query.filter_by(
        partner_id=partner.id, env=env, status='active'
    ).count()
    if active_key_count >= 10:
        flash(f'Maximum of 10 active {env} keys reached. Revoke unused keys first.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))

    try:
        full_key = _create_api_key_for_partner(partner, env)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to create API key")
        flash('An error occurred creating the API key. Please try again.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    session['partner_new_key'] = full_key
    flash('New API key created. Copy it now; it will not be shown again.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/keys/<int:key_id>/revoke', methods=['POST'])
@partner_login_required
def portal_revoke_key(key_id):
    partner = _current_partner()
    key = PartnerApiKey.query.filter_by(id=key_id, partner_id=partner.id).first_or_404()
    key.status = 'revoked'
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to revoke API key")
        flash('An error occurred. Please try again.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))
    flash('API key revoked.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/keys/<int:key_id>/rotate', methods=['POST'])
@partner_login_required
def portal_rotate_key(key_id):
    partner = _current_partner()
    key = PartnerApiKey.query.filter_by(id=key_id, partner_id=partner.id).first_or_404()
    if key.status != 'active':
        flash('Only active keys can be rotated.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))

    env = key.env
    if env == 'live' and partner.billing_status != 'active':
        flash('Live keys require an active subscription.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))

    # Revoke old key and create replacement in one transaction
    key.status = 'revoked'
    try:
        full_key = _create_api_key_for_partner(partner, env)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to rotate API key")
        flash('An error occurred rotating the key. Please try again.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    session['partner_new_key'] = full_key
    flash('API key rotated. Copy the new key now; it will not be shown again.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/billing/start', methods=['POST'])
@partner_login_required
def portal_start_billing():
    partner = _current_partner()
    try:
        checkout_session = create_partner_checkout_session(partner)
        if not checkout_session.url:
            flash('Payment session error. Please try again.', 'danger')
            return redirect(url_for('partner.portal_dashboard'))
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        current_app.logger.error(f"Partner checkout error: {e}")
        flash('Unable to start billing. Please try again.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/billing/portal')
@partner_login_required
def portal_billing_portal():
    partner = _current_partner()
    try:
        portal_session = create_partner_portal_session(partner)
        return redirect(portal_session.url, code=303)
    except Exception as e:
        current_app.logger.error(f"Partner portal error: {e}")
        flash('Unable to access billing portal.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/billing/success')
@partner_login_required
def portal_billing_success():
    partner = _current_partner()
    session_id = request.args.get('session_id')
    if not session_id:
        flash('Missing checkout session.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    try:
        s = get_stripe()
        checkout_session = s.checkout.Session.retrieve(session_id)
        if not partner.stripe_customer_id and checkout_session.customer:
            partner.stripe_customer_id = checkout_session.customer
            db.session.commit()
        if partner.stripe_customer_id and checkout_session.customer != partner.stripe_customer_id:
            flash('Invalid checkout session.', 'danger')
            return redirect(url_for('partner.portal_dashboard'))

        if checkout_session.subscription:
            sub_id = checkout_session.subscription if isinstance(checkout_session.subscription, str) else checkout_session.subscription.id
            stripe_sub = s.Subscription.retrieve(sub_id)
            status = stripe_sub.get('status') if isinstance(stripe_sub, dict) else stripe_sub.status
            partner.stripe_subscription_id = stripe_sub.get('id') if isinstance(stripe_sub, dict) else stripe_sub.id
            partner.billing_status = 'active' if status in ['active', 'trialing'] else 'inactive'
            db.session.commit()
            flash('Subscription active. You can now create live keys.', 'success')
        else:
            flash('Subscription is still being confirmed.', 'info')
    except Exception as e:
        current_app.logger.error(f"Partner billing success error: {e}")
        flash('Unable to confirm subscription. Please refresh later.', 'danger')

    return redirect(url_for('partner.portal_dashboard'))
