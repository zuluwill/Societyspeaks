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
from sqlalchemy.exc import IntegrityError
from flask import render_template, request, current_app, send_from_directory, redirect, url_for, flash, session, Response
from flask_login import current_user
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
from app.models import (
    Partner, PartnerDomain, PartnerApiKey, PartnerUsageEvent, PartnerMember, generate_slug
)
from app.billing.service import create_partner_checkout_session, create_partner_portal_session, get_stripe
from app.admin.audit import write_admin_audit_event
from app.lib.time import utcnow_naive


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
    partner = db.session.get(Partner, partner_id)
    if not partner or partner.status != 'active':
        # Clear stale session for deactivated/deleted partners
        _clear_partner_session()
        return None
    return partner


def _get_or_create_owner_member(partner):
    owner_member = PartnerMember.query.filter_by(
        partner_id=partner.id,
        email=partner.contact_email
    ).first()
    if owner_member:
        if owner_member.role != 'owner':
            owner_member.role = 'owner'
        if owner_member.status != 'active':
            owner_member.status = 'active'
        if not owner_member.password_hash:
            owner_member.password_hash = partner.password_hash
        return owner_member

    owner_member = PartnerMember(
        partner_id=partner.id,
        email=partner.contact_email,
        full_name=partner.name,
        password_hash=partner.password_hash,
        role='owner',
        status='active',
        accepted_at=utcnow_naive(),
    )
    db.session.add(owner_member)
    db.session.flush()
    return owner_member


def _current_partner_member(partner=None):
    partner = partner or _current_partner()
    if not partner:
        return None
    member_id = session.get('partner_member_id')
    if member_id:
        member = PartnerMember.query.filter_by(
            id=member_id,
            partner_id=partner.id,
            status='active'
        ).first()
        if member:
            return member
    return PartnerMember.query.filter_by(
        partner_id=partner.id,
        email=partner.contact_email,
        status='active'
    ).first()


def _member_can_manage_team(member):
    return bool(member and member.role in ('owner', 'admin'))


def _has_valid_admin_preview(partner):
    preview = session.get('partner_admin_preview') or {}
    if not preview or preview.get('partner_id') != partner.id:
        return False
    admin_user_id = preview.get('admin_user_id')
    if not admin_user_id:
        return False
    return bool(
        current_user.is_authenticated and
        getattr(current_user, 'is_admin', False) and
        current_user.id == admin_user_id
    )


def _is_admin_preview(partner):
    return _has_valid_admin_preview(partner)


def _log_admin_preview_event(partner, action, metadata=None):
    if not _is_admin_preview(partner):
        return
    preview = session.get('partner_admin_preview') or {}
    forwarded_for = request.headers.get('X-Forwarded-For', '')
    request_ip = (forwarded_for.split(',')[0].strip() if forwarded_for else (request.remote_addr or ''))[:64]
    write_admin_audit_event(
        admin_user_id=preview.get('admin_user_id'),
        action=action,
        target_type='partner',
        target_id=partner.id,
        request_ip=request_ip,
        metadata=metadata or {},
    )


def _is_partner_invite_expired(member):
    if not member or not member.invited_at:
        return True
    expiry_days = int(current_app.config.get('PARTNER_INVITE_EXPIRY_DAYS', 7) or 7)
    cutoff = utcnow_naive() - timedelta(days=expiry_days)
    return member.invited_at < cutoff


def _compute_partner_health(partner, keys, domains, usage):
    active_test_keys = [k for k in keys if k.env == 'test' and k.status == 'active']
    verified_test_domains = [d for d in domains if d.env == 'test' and d.is_verified() and d.is_active]
    create_count = int(usage.get('create', 0))
    lookup_count = int(usage.get('lookup', 0))
    snapshot_count = int(usage.get('snapshot', 0))

    checks = [
        {
            'id': 'auth',
            'label': 'Test key available',
            'ok': len(active_test_keys) > 0,
            'hint': 'Create a test API key in the API keys section.'
        },
        {
            'id': 'domain',
            'label': 'Verified test domain',
            'ok': len(verified_test_domains) > 0,
            'hint': 'Add a staging domain and verify DNS TXT.'
        },
        {
            'id': 'api_activity',
            'label': 'API activity detected',
            'ok': (create_count + lookup_count) > 0,
            'hint': 'Run one lookup or create call from your backend.'
        },
        {
            'id': 'billing',
            'label': 'Billing active for live',
            'ok': partner.billing_status == 'active',
            'hint': 'Activate a plan to enable live keys.'
        },
    ]

    return {
        'checks': checks,
        'counts': {
            'create': create_count,
            'lookup': lookup_count,
            'snapshot': snapshot_count,
        }
    }


def _build_partner_portal_context(partner):
    domains = partner.domains.order_by(PartnerDomain.created_at.desc()).all()
    keys = partner.api_keys.order_by(PartnerApiKey.created_at.desc()).all()
    has_verified_test_domain = any(d.env == 'test' and d.is_verified() and d.is_active for d in domains)
    has_test_key = any(k.env == 'test' and k.status == 'active' for k in keys)
    has_live_key = any(k.env == 'live' and k.status == 'active' for k in keys)
    return domains, keys, has_verified_test_domain, has_test_key, has_live_key


def _clear_partner_session():
    """Remove all partner-related keys from the session."""
    for key in list(session.keys()):
        if key.startswith('partner_'):
            session.pop(key, None)


def _safe_portal_next_url(next_url):
    """Return a safe local portal URL, or dashboard as fallback."""
    if not next_url:
        return url_for('partner.portal_dashboard')
    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        return url_for('partner.portal_dashboard')
    if not next_url.startswith('/for-publishers/portal'):
        return url_for('partner.portal_dashboard')
    return next_url


def partner_login_required(f):
    """Decorator that ensures the user is logged in to the partner portal."""
    @wraps(f)
    def decorated(*args, **kwargs):
        partner = _current_partner()
        if not partner:
            flash('Please sign in to the Partner Portal.', 'warning')
            return redirect(url_for('partner.portal_login', next=request.full_path))
        if session.get('partner_admin_preview') and not _has_valid_admin_preview(partner):
            _clear_partner_session()
            flash('Your admin preview session expired. Please re-open it from Admin.', 'warning')
            return redirect(url_for('partner.portal_login'))

        if _is_admin_preview(partner) and request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            _log_admin_preview_event(partner, 'partner_preview_write_blocked', {
                'path': request.path,
                'method': request.method,
            })
            flash('Read-only preview mode: write actions are disabled.', 'warning')
            return redirect(url_for('partner.portal_dashboard'))
        member_id = session.get('partner_member_id')
        if member_id:
            active_member = PartnerMember.query.filter_by(
                id=member_id, partner_id=partner.id, status='active'
            ).first()
            if not active_member:
                _clear_partner_session()
                flash('Your team access is no longer active. Please sign in again.', 'warning')
                return redirect(url_for('partner.portal_login'))
        else:
            owner_member = _get_or_create_owner_member(partner)
            db.session.commit()
            session['partner_member_id'] = owner_member.id
        return f(*args, **kwargs)
    return decorated


def _get_base_url():
    """Return the configured base URL (DRY helper used by public + portal routes)."""
    return current_app.config.get('BASE_URL', 'https://societyspeaks.io')


def _validate_env(raw_env):
    """Normalize and validate an env parameter. Returns 'test' or 'live'."""
    return raw_env if raw_env in ('test', 'live') else 'test'


def _validate_tier(raw_tier):
    """Normalize and validate a pricing tier. Returns 'starter' or 'professional'."""
    return raw_tier if raw_tier in ('starter', 'professional') else 'starter'


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

        # PartnerMember.email is globally unique across all partners.
        # Check before insert to avoid integrity errors when a user was invited already.
        if PartnerMember.query.filter_by(email=email).first():
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
            owner_member = _get_or_create_owner_member(partner)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('An account with this email already exists. Please sign in.', 'warning')
            return redirect(url_for('partner.portal_login'))
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to create partner account")
            flash('An error occurred creating your account. Please try again.', 'danger')
            return render_template('partner/portal/signup.html')

        session['partner_portal_id'] = partner.id
        session['partner_member_id'] = owner_member.id
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

        member = PartnerMember.query.filter_by(email=email).first()
        partner = member.partner if member else Partner.query.filter_by(contact_email=email).first()

        # Temporary lockout after repeated failures (stored in session to keep it simple)
        # Uses '_lockout_' prefix (not 'partner_') so _clear_partner_session() won't wipe it
        lockout_key = f'_lockout_partner:{email}'
        fail_count = session.get(lockout_key, 0)
        lockout_until = session.get(f'{lockout_key}:until')

        if lockout_until:
            lockout_dt = datetime.fromisoformat(lockout_until)
            if utcnow_naive() < lockout_dt:
                remaining = int((lockout_dt - utcnow_naive()).total_seconds())
                flash(f'Too many failed attempts. Please try again in {remaining} seconds.', 'danger')
                return render_template('partner/portal/login.html')
            else:
                # Lockout expired, reset
                session.pop(lockout_key, None)
                session.pop(f'{lockout_key}:until', None)
                fail_count = 0

        valid_login = False
        if member:
            if member.status == 'active' and partner and partner.status == 'active':
                # Owner credentials are sourced from Partner for backward compatibility.
                if member.role == 'owner' or member.email == partner.contact_email:
                    valid_login = partner.check_password(password)
                    if valid_login and member.password_hash != partner.password_hash:
                        member.password_hash = partner.password_hash
                else:
                    valid_login = member.check_password(password)
        elif partner:
            valid_login = partner.check_password(password)

        if not partner or not valid_login:
            fail_count += 1
            session[lockout_key] = fail_count
            if fail_count >= 5:
                # Lock out for 5 minutes after 5 failures
                lockout_dt = utcnow_naive() + timedelta(minutes=5)
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

        owner_member = _get_or_create_owner_member(partner)
        if member and member.partner_id == partner.id and member.status == 'active':
            active_member = member
        else:
            active_member = owner_member
        active_member.last_login_at = utcnow_naive()
        db.session.commit()

        session['partner_portal_id'] = partner.id
        session['partner_member_id'] = active_member.id
        flash('Welcome back.', 'success')
        next_url = request.form.get('next') or request.args.get('next')
        return redirect(_safe_portal_next_url(next_url))

    return render_template('partner/portal/login.html', next_url=request.args.get('next'))


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
@limiter.limit("5 per 15 minutes")
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
            owner_member = _get_or_create_owner_member(partner)
            owner_member.set_password(password)
            owner_member.status = 'active'
            owner_member.accepted_at = owner_member.accepted_at or utcnow_naive()
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to reset partner password")
            flash('An error occurred. Please try again.', 'danger')
            return render_template('partner/portal/reset_password.html', token=token)

        session['partner_portal_id'] = partner.id
        session['partner_member_id'] = owner_member.id
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
    current_member = _current_partner_member(partner)
    domains, keys, has_verified_test_domain, has_test_key, has_live_key = _build_partner_portal_context(partner)
    new_key = session.pop('partner_new_key', None)
    dns_checks = session.get('partner_dns_checks', {})

    since = utcnow_naive() - timedelta(days=30)
    usage_rows = PartnerUsageEvent.query.filter(
        PartnerUsageEvent.partner_id == partner.id,
        PartnerUsageEvent.created_at >= since
    ).with_entities(
        PartnerUsageEvent.event_type,
        func.sum(PartnerUsageEvent.quantity)
    ).group_by(PartnerUsageEvent.event_type).all()
    usage = {row[0]: int(row[1] or 0) for row in usage_rows}
    partner_health = _compute_partner_health(partner, keys, domains, usage)
    last_health_check = session.get('partner_last_health_check')
    last_health_result = session.get('partner_last_health_result')
    team_members = PartnerMember.query.filter_by(partner_id=partner.id).order_by(PartnerMember.created_at.asc()).all()

    daily_since = utcnow_naive() - timedelta(days=13)
    daily_rows = PartnerUsageEvent.query.filter(
        PartnerUsageEvent.partner_id == partner.id,
        PartnerUsageEvent.created_at >= daily_since
    ).with_entities(
        func.date(PartnerUsageEvent.created_at).label('day'),
        func.sum(PartnerUsageEvent.quantity)
    ).group_by('day').all()
    daily_map = {str(row[0]): int(row[1] or 0) for row in daily_rows}
    today = utcnow_naive().date()
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
        is_admin_preview=_is_admin_preview(partner),
        current_member=current_member,
        can_manage_team=_member_can_manage_team(current_member),
        team_members=team_members,
        partner_health=partner_health,
        last_health_check=last_health_check,
        last_health_result=last_health_result,
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
    current_member = _current_partner_member(partner)
    domains, keys, has_verified_test_domain, has_test_key, has_live_key = _build_partner_portal_context(partner)
    return render_template(
        'partner/portal/getting_started.html',
        partner=partner,
        is_admin_preview=_is_admin_preview(partner),
        current_member=current_member,
        can_manage_team=_member_can_manage_team(current_member),
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
    current_member = _current_partner_member(partner)
    domains, keys, has_verified_test_domain, has_test_key, has_live_key = _build_partner_portal_context(partner)
    return render_template(
        'partner/portal/success.html',
        partner=partner,
        is_admin_preview=_is_admin_preview(partner),
        current_member=current_member,
        can_manage_team=_member_can_manage_team(current_member),
        domains=domains,
        keys=keys,
        has_verified_test_domain=has_verified_test_domain,
        has_test_key=has_test_key,
        has_live_key=has_live_key,
        base_url=_get_base_url()
    )


@partner_bp.route('/portal/health-check', methods=['POST'])
@partner_login_required
def portal_health_check():
    partner = _current_partner()
    domains, keys, _, _, _ = _build_partner_portal_context(partner)

    from sqlalchemy import func
    since = utcnow_naive() - timedelta(days=30)
    usage_rows = PartnerUsageEvent.query.filter(
        PartnerUsageEvent.partner_id == partner.id,
        PartnerUsageEvent.created_at >= since
    ).with_entities(
        PartnerUsageEvent.event_type,
        func.sum(PartnerUsageEvent.quantity)
    ).group_by(PartnerUsageEvent.event_type).all()
    usage = {row[0]: int(row[1] or 0) for row in usage_rows}
    health = _compute_partner_health(partner, keys, domains, usage)
    session['partner_last_health_check'] = utcnow_naive().isoformat()
    session['partner_last_health_result'] = health
    session.modified = True
    flash('Integration health check updated.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/usage.csv')
@limiter.limit("10 per minute")
@partner_login_required
def portal_usage_csv():
    from sqlalchemy import func
    import csv
    from io import StringIO

    partner = _current_partner()
    since = utcnow_naive() - timedelta(days=90)
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


def _send_partner_member_invite_email(partner, email, invite_url, inviter_name=None):
    from app.resend_client import get_resend_client
    client = get_resend_client()
    email_data = {
        'from': f"Society Speaks <noreply@{current_app.config.get('RESEND_DOMAIN', 'societyspeaks.io')}>",
        'to': [email],
        'subject': f"You've been invited to {partner.name} on Society Speaks",
        'html': render_template(
            'emails/partner_member_invite.html',
            partner=partner,
            invite_url=invite_url,
            inviter_name=inviter_name or partner.name,
        ),
    }
    return client._send_with_retry(email_data)


@partner_bp.route('/portal/team/invite', methods=['POST'])
@limiter.limit("10 per hour")
@partner_login_required
def portal_invite_member():
    partner = _current_partner()
    current_member = _current_partner_member(partner)
    if not _member_can_manage_team(current_member):
        flash('Only owners and admins can invite team members.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    email = normalize_email(request.form.get('email'))
    role = request.form.get('role', 'member')
    full_name = (request.form.get('full_name') or '').strip()
    if role not in ('admin', 'member'):
        role = 'member'

    email_ok, email_err = validate_email_format(email)
    if not email_ok:
        flash(email_err, 'danger')
        return redirect(url_for('partner.portal_dashboard'))
    if email == partner.contact_email:
        flash('The owner email already has access.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))

    existing = PartnerMember.query.filter_by(email=email).first()
    if existing and existing.partner_id != partner.id:
        flash('That email is already linked to another partner account.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))
    if existing and existing.status == 'active':
        flash('That team member already has access.', 'info')
        return redirect(url_for('partner.portal_dashboard'))

    token = PartnerMember.generate_invite_token()
    if existing:
        member = existing
        member.role = role
        member.status = 'pending'
        member.full_name = full_name or member.full_name
        member.invite_token = token
        member.invited_at = utcnow_naive()
    else:
        member = PartnerMember(
            partner_id=partner.id,
            email=email,
            full_name=full_name or None,
            role=role,
            status='pending',
            invite_token=token,
            invited_at=utcnow_naive(),
        )
        db.session.add(member)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to save partner invite")
        flash('Could not create invite. Please try again.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    invite_url = url_for('partner.portal_accept_invite', token=token, _external=True)
    try:
        _send_partner_member_invite_email(
            partner=partner,
            email=email,
            invite_url=invite_url,
            inviter_name=current_member.full_name if current_member else None
        )
    except Exception:
        current_app.logger.exception("Failed to send partner member invite email")
        flash('Invite saved, but email delivery failed. Copy the invite link from logs or retry.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))

    flash(f'Invite sent to {email}.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/team/accept/<token>', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
def portal_accept_invite(token):
    member = PartnerMember.query.filter_by(invite_token=token, status='pending').first()
    if not member or _is_partner_invite_expired(member):
        flash('This invite link is invalid or expired.', 'danger')
        return redirect(url_for('partner.portal_login'))
    partner = db.session.get(Partner, member.partner_id)
    if not partner or partner.status != 'active':
        flash('This partner account is not active.', 'danger')
        return redirect(url_for('partner.portal_login'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        full_name = (request.form.get('full_name') or '').strip()
        is_valid, error_message = validate_password(password)
        if not is_valid:
            flash(error_message, 'danger')
            return render_template('partner/portal/accept_invite.html', member=member, partner=partner, token=token)

        member.set_password(password)
        member.full_name = full_name[:150] if full_name else (member.full_name or member.email)
        member.status = 'active'
        member.accepted_at = utcnow_naive()
        member.invite_token = None
        member.last_login_at = utcnow_naive()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to accept partner invite")
            flash('Could not accept invite. Please try again.', 'danger')
            return render_template('partner/portal/accept_invite.html', member=member, partner=partner, token=token)

        session['partner_portal_id'] = partner.id
        session['partner_member_id'] = member.id
        flash('Welcome to the partner portal.', 'success')
        return redirect(url_for('partner.portal_dashboard'))

    return render_template('partner/portal/accept_invite.html', member=member, partner=partner, token=token)


@partner_bp.route('/portal/team/<int:member_id>/status', methods=['POST'])
@partner_login_required
def portal_update_member_status(member_id):
    partner = _current_partner()
    current_member = _current_partner_member(partner)
    if not _member_can_manage_team(current_member):
        flash('Only owners and admins can update team members.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    member = PartnerMember.query.filter_by(id=member_id, partner_id=partner.id).first_or_404()
    if member.role == 'owner':
        flash('Owner access cannot be changed.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))
    if current_member and current_member.id == member.id:
        flash('You cannot disable your own access.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))

    action = request.form.get('action')
    if action == 'disable':
        member.status = 'disabled'
    elif action == 'enable':
        member.status = 'active'
    else:
        flash('Unsupported action.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to update partner member status")
        flash('Could not update member status.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))
    flash('Member updated.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/team/<int:member_id>/role', methods=['POST'])
@partner_login_required
def portal_update_member_role(member_id):
    partner = _current_partner()
    current_member = _current_partner_member(partner)
    if not _member_can_manage_team(current_member):
        flash('Only owners and admins can update roles.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    member = PartnerMember.query.filter_by(id=member_id, partner_id=partner.id).first_or_404()
    if member.role == 'owner':
        flash('Owner role cannot be changed.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))

    role = request.form.get('role', 'member')
    if role not in ('admin', 'member'):
        flash('Invalid role.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    member.role = role
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to update partner member role")
        flash('Could not update role.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))
    flash('Role updated.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/domains/add', methods=['POST'])
@limiter.limit("10 per minute")
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


@partner_bp.route('/portal/domains/<int:domain_id>/toggle', methods=['POST'])
@partner_login_required
def portal_toggle_domain(domain_id):
    partner = _current_partner()
    domain = PartnerDomain.query.filter_by(id=domain_id, partner_id=partner.id).first_or_404()
    domain.is_active = not bool(domain.is_active)
    if not domain.is_active:
        # Deactivated domains should not remain verified for origin allowlists.
        domain.verified_at = None
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to toggle domain status")
        flash('Could not update domain status.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))
    if domain.is_active:
        flash('Domain activated. Re-verify DNS TXT before embed requests are allowed.', 'success')
    else:
        flash('Domain deactivated.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/domains/<int:domain_id>/remove', methods=['POST'])
@partner_login_required
def portal_remove_domain(domain_id):
    partner = _current_partner()
    domain = PartnerDomain.query.filter_by(id=domain_id, partner_id=partner.id).first_or_404()
    try:
        db.session.delete(domain)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to remove partner domain")
        flash('Could not remove domain.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))
    flash('Domain removed.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/domains/<int:domain_id>/verify', methods=['POST'])
@partner_login_required
def portal_verify_domain(domain_id):
    partner = _current_partner()
    domain = PartnerDomain.query.filter_by(id=domain_id, partner_id=partner.id).first_or_404()
    if not domain.is_active:
        flash('Activate this domain before verifying.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))
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
            if (utcnow_naive() - prev_dt).total_seconds() < cooldown_seconds:
                flash('Please wait 30 seconds between verification attempts.', 'warning')
                return redirect(url_for('partner.portal_dashboard'))
        except (ValueError, TypeError):
            pass  # Malformed date in session, allow the check

    verified, details = _verify_dns_txt(domain.domain, domain.verification_token)
    dns_checks[str(domain.id)] = {
        'checked_at': utcnow_naive().isoformat(),
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
        domain.verified_at = utcnow_naive()
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
    if partner.billing_status == 'active':
        flash('You already have an active subscription. Use Manage Billing to change plans.', 'info')
        return redirect(url_for('partner.portal_dashboard'))
    tier = _validate_tier(request.form.get('tier', 'starter'))
    try:
        checkout_session = create_partner_checkout_session(partner, tier=tier)
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
        metadata = checkout_session.get('metadata', {}) if isinstance(checkout_session, dict) else (checkout_session.metadata or {})
        meta_partner_id = metadata.get('partner_id')
        if meta_partner_id:
            try:
                if int(meta_partner_id) != partner.id:
                    flash('Invalid checkout session.', 'danger')
                    return redirect(url_for('partner.portal_dashboard'))
            except (TypeError, ValueError):
                flash('Invalid checkout session.', 'danger')
                return redirect(url_for('partner.portal_dashboard'))

        customer_id = checkout_session.customer if not isinstance(checkout_session, dict) else checkout_session.get('customer')
        if partner.stripe_customer_id and customer_id and customer_id != partner.stripe_customer_id:
            flash('Invalid checkout session.', 'danger')
            return redirect(url_for('partner.portal_dashboard'))
        if not partner.stripe_customer_id and customer_id:
            partner.stripe_customer_id = customer_id

        if checkout_session.subscription:
            sub_id = checkout_session.subscription if isinstance(checkout_session.subscription, str) else checkout_session.subscription.id
            stripe_sub = s.Subscription.retrieve(sub_id)
            status = stripe_sub.get('status') if isinstance(stripe_sub, dict) else stripe_sub.status
            if status in ('canceled', 'unpaid', 'incomplete_expired'):
                partner.stripe_subscription_id = None
            else:
                partner.stripe_subscription_id = stripe_sub.get('id') if isinstance(stripe_sub, dict) else stripe_sub.id
            partner.billing_status = 'active' if status in ['active', 'trialing', 'past_due'] else 'inactive'

            # Sync tier from checkout metadata to close the webhook race window
            metadata = checkout_session.get('metadata', {}) if isinstance(checkout_session, dict) else (checkout_session.metadata or {})
            tier_from_meta = metadata.get('partner_tier')
            if tier_from_meta in ('starter', 'professional', 'enterprise'):
                partner.tier = tier_from_meta
            elif partner.billing_status == 'active' and partner.tier == 'free':
                partner.tier = 'starter'  # legacy fallback

            if status in ('canceled', 'unpaid', 'incomplete_expired'):
                partner.tier = 'free'

            db.session.commit()
            flash('Subscription active. You can now create live keys.', 'success')
        else:
            flash('Subscription is still being confirmed.', 'info')
    except Exception as e:
        current_app.logger.error(f"Partner billing success error: {e}")
        flash('Unable to confirm subscription. Please refresh later.', 'danger')

    return redirect(url_for('partner.portal_dashboard'))
