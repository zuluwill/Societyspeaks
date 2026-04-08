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
from sqlalchemy import desc, func

from app.models import (
    Partner, PartnerDomain, PartnerApiKey, PartnerUsageEvent, PartnerMember, generate_slug,
    Discussion, Statement, StatementVote, ConsensusAnalysis, PartnerWebhookEndpoint, PartnerWebhookDelivery,
)
from app.billing.service import create_partner_checkout_session, create_partner_portal_session, get_stripe
from app.api.utils import invalidate_partner_snapshot_cache
from app.admin.audit import write_admin_audit_event
from app.lib.time import utcnow_naive
from app.partner.permissions import (
    member_can,
    member_permissions,
    ALL_PERMISSIONS,
    PERMISSION_OPTIONS,
    PERM_KEYS_MANAGE,
    PERM_DISCUSSIONS_MANAGE,
    PERM_ANALYTICS_VIEW,
    PERM_TEAM_MANAGE,
    PERM_DOMAINS_MANAGE,
    PERM_BILLING_MANAGE,
    PERM_WEBHOOKS_MANAGE,
)
from app.partner.events import (
    EVENT_DISCUSSION_UPDATED,
    EVENT_KEY_REVOKED,
    EVENT_DOMAIN_VERIFICATION_CHANGED,
    ALL_PARTNER_EVENTS,
    serialize_discussion_payload,
    serialize_key_payload,
    serialize_domain_payload,
)
from app.partner.webhooks import generate_webhook_secret, emit_partner_event, send_test_delivery


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
    return member_can(member, PERM_TEAM_MANAGE)


def _member_can_manage_keys(member):
    return member_can(member, PERM_KEYS_MANAGE)


def _member_can_manage_discussions(member):
    return member_can(member, PERM_DISCUSSIONS_MANAGE)


def _member_can_view_analytics(member):
    return member_can(member, PERM_ANALYTICS_VIEW)


def _member_can_manage_domains(member):
    return member_can(member, PERM_DOMAINS_MANAGE)


def _member_can_manage_billing(member):
    return member_can(member, PERM_BILLING_MANAGE)


def _member_can_manage_webhooks(member):
    return member_can(member, PERM_WEBHOOKS_MANAGE)


def _permissions_from_form():
    return {key: bool(request.form.get(key)) for key in ALL_PERMISSIONS}


def _form_bool(field_name):
    return (request.form.get(field_name) or '').strip().lower() in ('1', 'true', 'on', 'yes')


def _portal_discussion_belongs_clause(partner):
    """SQL filter for discussions owned by this partner (FK or legacy slug)."""
    return db.or_(
        Discussion.partner_fk_id == partner.id,
        Discussion.partner_id == partner.slug,
    )


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
    management_count = sum(
        int(usage.get(et, 0) or 0)
        for et in (
            'list_discussions',
            'list_flags',
            'patch_discussion',
            'add_statements',
        )
    )

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
            # Snapshots omitted: read-only embed traffic, not editorial/backend integration.
            'ok': (create_count + lookup_count + management_count) > 0,
            'hint': 'Run one lookup, create, or management API call from your backend.'
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
            'management': management_count,
        }
    }


def _partner_discussion_quota(partner):
    """Live discussions this calendar month vs tier cap; test lifetime count."""
    from datetime import datetime, timezone

    tier_limits = current_app.config.get('PARTNER_TIER_LIMITS', {})
    tier = getattr(partner, 'tier', 'free') or 'free'
    limit = tier_limits.get(tier, 25)
    month_start = datetime.now(timezone.utc).replace(
        tzinfo=None, day=1, hour=0, minute=0, second=0, microsecond=0
    )
    live_used = Discussion.query.filter(
        Discussion.partner_fk_id == partner.id,
        Discussion.partner_env == 'live',
        Discussion.created_at >= month_start,
    ).count()
    test_used = Discussion.query.filter_by(
        partner_fk_id=partner.id, partner_env='test'
    ).count()
    return {
        'tier': tier,
        'live_limit': limit,
        'live_used_month': live_used,
        'test_used_lifetime': test_used,
    }


def _check_partner_quota_for_env(partner, env):
    """
    Check whether the partner has capacity to create another discussion.
    Returns None if within quota, or a human-readable error string if capped.
    Mirrors _partner_discussion_quota and the API enforcement — uses UTC month start.
    """
    from datetime import timezone
    tier_limits = current_app.config.get('PARTNER_TIER_LIMITS', {})
    partner_tier = getattr(partner, 'tier', 'free') or 'free'
    tier_limit = tier_limits.get(partner_tier, 25)

    if tier_limit is None:
        return None  # Enterprise — no cap

    if env == 'test':
        count = Discussion.query.filter_by(partner_fk_id=partner.id, partner_env='test').count()
    else:
        month_start = datetime.now(timezone.utc).replace(
            tzinfo=None, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        count = Discussion.query.filter(
            Discussion.partner_fk_id == partner.id,
            Discussion.partner_env == 'live',
            Discussion.created_at >= month_start,
        ).count()

    if count >= tier_limit:
        return (
            f'Discussion quota reached for your {partner_tier.title()} plan '
            f'({count}/{tier_limit}). Upgrade to create more.'
        )
    return None


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

        # Capture redirect target before clearing the session.
        next_url = request.form.get('next') or request.args.get('next')

        # Regenerate session to prevent session-fixation attacks.
        # Clear all pre-login state (lockout counters, DNS check cache, etc.)
        # before writing the authenticated partner/member IDs.
        session.clear()

        owner_member = _get_or_create_owner_member(partner)
        if member and member.partner_id == partner.id and member.status == 'active':
            active_member = member
        else:
            active_member = owner_member
        active_member.last_login_at = utcnow_naive()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('portal_login: failed to update last_login_at')

        session['partner_portal_id'] = partner.id
        session['partner_member_id'] = active_member.id
        flash('Welcome back.', 'success')
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
    partner = _current_partner()
    current_member = _current_partner_member(partner)
    domains, keys, has_verified_test_domain, has_test_key, has_live_key = _build_partner_portal_context(partner)
    new_key = session.pop('partner_new_key', None)
    new_webhook_secret = session.pop('partner_new_webhook_secret', None)
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
    for m in team_members:
        m.effective_permissions = member_permissions(m)

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
    partner_quota = _partner_discussion_quota(partner)
    webhooks = PartnerWebhookEndpoint.query.filter_by(partner_id=partner.id).order_by(PartnerWebhookEndpoint.created_at.desc()).all()
    recent_deliveries = PartnerWebhookDelivery.query.filter_by(partner_id=partner.id).order_by(PartnerWebhookDelivery.created_at.desc()).limit(20).all()
    current_perms = member_permissions(current_member)
    return render_template(
        'partner/portal/dashboard.html',
        partner=partner,
        partner_quota=partner_quota,
        domains=domains,
        keys=keys,
        new_key=new_key,
        new_webhook_secret=new_webhook_secret,
        has_verified_test_domain=has_verified_test_domain,
        has_test_key=has_test_key,
        has_live_key=has_live_key,
        is_admin_preview=_is_admin_preview(partner),
        current_member=current_member,
        can_manage_team=_member_can_manage_team(current_member),
        can_manage_keys=_member_can_manage_keys(current_member),
        can_manage_discussions=_member_can_manage_discussions(current_member),
        can_view_analytics=_member_can_view_analytics(current_member),
        can_manage_domains=_member_can_manage_domains(current_member),
        can_manage_billing=_member_can_manage_billing(current_member),
        can_manage_webhooks=_member_can_manage_webhooks(current_member),
        current_member_permissions=current_perms,
        permission_options=PERMISSION_OPTIONS,
        team_members=team_members,
        webhooks=webhooks,
        recent_webhook_deliveries=recent_deliveries,
        all_webhook_events=sorted(ALL_PARTNER_EVENTS),
        partner_health=partner_health,
        last_health_check=last_health_check,
        last_health_result=last_health_result,
        usage=usage,
        usage_daily=usage_daily,
        usage_max=usage_max,
        dns_checks=dns_checks,
        base_url=_get_base_url(),
        portal_page='dashboard',
    )


@partner_bp.route('/portal/discussions')
@partner_login_required
def portal_discussions():
    partner = _current_partner()

    env_filter = (request.args.get('env') or 'all').lower()
    if env_filter not in ('test', 'live', 'all'):
        env_filter = 'all'
    status_filter = (request.args.get('status') or 'all').lower()
    if status_filter not in ('open', 'closed', 'all'):
        status_filter = 'all'
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    q = Discussion.query.filter(_portal_discussion_belongs_clause(partner))
    if env_filter != 'all':
        q = q.filter(Discussion.partner_env == env_filter)
    if status_filter == 'open':
        q = q.filter(Discussion.is_closed == False)  # noqa: E712
    elif status_filter == 'closed':
        q = q.filter(Discussion.is_closed == True)  # noqa: E712

    pagination = q.order_by(Discussion.created_at.desc()).paginate(page=page, per_page=25, error_out=False)
    discussions = pagination.items

    d_ids = [d.id for d in discussions]
    vote_counts = {}
    if d_ids:
        rows = (
            db.session.query(StatementVote.discussion_id, func.count(StatementVote.id))
            .filter(StatementVote.discussion_id.in_(d_ids))
            .group_by(StatementVote.discussion_id)
            .all()
        )
        vote_counts = {int(r[0]): int(r[1]) for r in rows}

    base = _get_base_url()
    can_edit = _member_can_manage_discussions(_current_partner_member(partner)) and not _is_admin_preview(partner)

    # Batch-fetch key info for audit column — scoped to this partner in SQL (defence in depth)
    key_ids = [d.created_by_key_id for d in discussions if d.created_by_key_id]
    key_map = {}
    if key_ids:
        keys = PartnerApiKey.query.filter(
            PartnerApiKey.id.in_(key_ids),
            PartnerApiKey.partner_id == partner.id,
        ).all()
        key_map = {k.id: k for k in keys}

    rows_out = []
    for d in discussions:
        key_rec = key_map.get(d.created_by_key_id) if d.created_by_key_id else None
        rows_out.append({
            'discussion': d,
            'vote_count': vote_counts.get(d.id, 0),
            'embed_url': f"{base}/discussions/{d.id}/embed?ref={partner.slug}",
            'consensus_url': f"{base}/discussions/{d.id}/{d.slug}/consensus?ref={partner.slug}",
            'key_label': f"••••{key_rec.key_last4}" if key_rec else None,
        })

    return render_template(
        'partner/portal/discussions.html',
        partner=partner,
        rows=rows_out,
        pagination=pagination,
        env_filter=env_filter,
        status_filter=status_filter,
        partner_quota=_partner_discussion_quota(partner),
        base_url=base,
        can_edit=can_edit,
        can_create=_member_can_manage_discussions(_current_partner_member(partner)) and not _is_admin_preview(partner),
        is_admin_preview=_is_admin_preview(partner),
        discussion_topics=Discussion.TOPICS,
        portal_page='discussions',
    )


@partner_bp.route('/portal/discussions/new', methods=['POST'])
@partner_login_required
def portal_create_discussion():
    """Create a discussion directly from the portal UI (no API key required)."""
    partner = _current_partner()
    member = _current_partner_member(partner)

    if not _member_can_manage_discussions(member):
        flash('You do not have permission to create discussions.', 'error')
        return redirect(url_for('partner.portal_discussions'))

    if _is_admin_preview(partner):
        flash('Admin preview mode: create actions are disabled.', 'warning')
        return redirect(url_for('partner.portal_discussions'))

    title = (request.form.get('title') or '').strip()
    article_url = (request.form.get('article_url') or '').strip()
    external_id = (request.form.get('external_id') or '').strip()
    excerpt = (request.form.get('excerpt') or '').strip()
    description = (request.form.get('description') or '').strip()
    topic = (request.form.get('topic') or '').strip()
    env = (request.form.get('env') or 'test').strip()
    embed_submissions_enabled = _form_bool('embed_statement_submissions_enabled')

    if env not in ('test', 'live'):
        env = 'test'

    if not title:
        flash('Title is required.', 'error')
        return redirect(url_for('partner.portal_discussions'))

    max_title_len = (getattr(Discussion.__table__.c.title.type, 'length', None) or 200)
    if len(title) > max_title_len:
        flash(f'Title must be {max_title_len} characters or fewer.', 'error')
        return redirect(url_for('partner.portal_discussions'))

    if not article_url and not external_id:
        flash('Either an article URL or an external ID is required.', 'error')
        return redirect(url_for('partner.portal_discussions'))

    if env == 'live' and partner.billing_status != 'active':
        flash('An active subscription is required to create live discussions.', 'error')
        return redirect(url_for('partner.portal_discussions'))

    if topic and topic not in Discussion.TOPICS:
        topic = ''

    # Quota check (DRY — shared with API)
    quota_err = _check_partner_quota_for_env(partner, env)
    if quota_err:
        flash(quota_err, 'error')
        return redirect(url_for('partner.portal_discussions'))

    # Normalise article URL
    normalized_url = None
    if article_url:
        if len(article_url) > 2048:
            flash('Article URL must be 2048 characters or fewer.', 'error')
            return redirect(url_for('partner.portal_discussions'))
        try:
            from app.lib.url_normalizer import normalize_url
            normalized_url = normalize_url(article_url)
        except Exception:
            flash('Invalid article URL — please check and try again.', 'error')
            return redirect(url_for('partner.portal_discussions'))

        existing = Discussion.query.filter_by(
            partner_article_url=normalized_url,
            partner_env=env,
            partner_fk_id=partner.id,
        ).first()
        if existing:
            flash(f'A discussion already exists for that article URL (ID {existing.id}).', 'warning')
            return redirect(url_for('partner.portal_discussions'))

    # External ID uniqueness
    if external_id:
        max_external_id_len = (
            getattr(Discussion.__table__.c.partner_external_id.type, 'length', None) or 128
        )
        if len(external_id) > max_external_id_len:
            flash(f'External ID must be {max_external_id_len} characters or fewer.', 'error')
            return redirect(url_for('partner.portal_discussions'))
        existing = Discussion.query.filter_by(
            partner_external_id=external_id,
            partner_fk_id=partner.id,
            partner_env=env,
        ).first()
        if existing:
            flash(f'A discussion with that external ID already exists (ID {existing.id}).', 'warning')
            return redirect(url_for('partner.portal_discussions'))

    # Best active key for audit trail
    best_key = PartnerApiKey.query.filter_by(
        partner_id=partner.id, env=env, status='active'
    ).order_by(PartnerApiKey.created_at.desc()).first()

    # Generate slug (retry on collision)
    from app.trending.constants import get_unique_slug
    base_slug = generate_slug(title) or 'discussion'
    unique_slug = get_unique_slug(Discussion, base_slug)

    discussion = Discussion(
        title=title,
        description=(description[:1000] if description else (excerpt[:500] if excerpt else None)),
        slug=unique_slug,
        topic=topic or None,
        has_native_statements=True,
        geographic_scope='global',
        partner_id=partner.slug,
        partner_fk_id=partner.id,
        partner_env=env,
        partner_article_url=normalized_url,
        partner_external_id=external_id or None,
        embed_statement_submissions_enabled=embed_submissions_enabled,
        created_by_key_id=best_key.id if best_key else None,
    )
    db.session.add(discussion)

    if excerpt:
        try:
            from app.trending.seed_generator import generate_seed_statements_from_content
            seeds = generate_seed_statements_from_content(
                title=title,
                excerpt=excerpt[:5000],  # Mirror API _CREATE_MAX_EXCERPT cap
                source_name=partner.name,
            )
            for s in seeds:
                stmt = Statement(
                    content=s.get('content', ''),
                    seed_stance=s.get('position') or s.get('stance'),
                    statement_type='claim',
                    is_seed=True,
                    mod_status=1,
                    source='ai_generated',
                )
                discussion.statements.append(stmt)
        except Exception:
            current_app.logger.exception(
                "Seed generation failed for portal discussion (partner=%s)", partner.slug
            )

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash('Could not create the discussion — a duplicate may already exist.', 'error')
        return redirect(url_for('partner.portal_discussions'))

    flash(f'Discussion "{title}" created successfully (ID {discussion.id}).', 'success')
    return redirect(url_for('partner.portal_discussion_detail', discussion_id=discussion.id))


@partner_bp.route('/portal/discussions/<int:discussion_id>/toggle-closed', methods=['POST'])
@partner_login_required
def portal_toggle_discussion_closed(discussion_id):
    """Allow admin/owner to open or close a discussion from the portal."""
    partner = _current_partner()
    if not _member_can_manage_discussions(_current_partner_member(partner)):
        flash('You do not have permission to open or close discussions.', 'warning')
        return redirect(url_for('partner.portal_discussions'))

    if _is_admin_preview(partner):
        flash('Admin preview is read-only.', 'warning')
        return redirect(url_for('partner.portal_discussions'))

    discussion = Discussion.query.filter(
        Discussion.id == discussion_id,
        _portal_discussion_belongs_clause(partner),
    ).first_or_404()

    discussion.is_closed = not discussion.is_closed
    try:
        db.session.commit()
        invalidate_partner_snapshot_cache(discussion_id)
        action = 'closed' if discussion.is_closed else 'reopened'
        try:
            emit_partner_event(
                partner_id=partner.id,
                event_type=EVENT_DISCUSSION_UPDATED,
                data=serialize_discussion_payload(discussion),
            )
        except Exception:
            current_app.logger.exception("Failed to emit discussion.updated from portal toggle")
        flash(f'Discussion #{discussion_id} {action}.', 'success')
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to toggle discussion closed state")
        flash('An error occurred. Please try again.', 'danger')

    return redirect(url_for('partner.portal_discussions',
                            env=request.args.get('env', 'all'),
                            status=request.args.get('status', 'all'),
                            page=request.args.get('page', 1)))


@partner_bp.route('/portal/discussions/<int:discussion_id>')
@partner_login_required
def portal_discussion_detail(discussion_id):
    """Per-discussion analytics: statement vote breakdown, consensus status, audit info."""
    partner = _current_partner()
    discussion = Discussion.query.filter(
        Discussion.id == discussion_id,
        _portal_discussion_belongs_clause(partner),
    ).first_or_404()

    vote_total = (
        Statement.vote_count_agree
        + Statement.vote_count_disagree
        + Statement.vote_count_unsure
    )
    statements = (
        Statement.query
        .filter_by(discussion_id=discussion_id, is_deleted=False)
        .filter(Statement.mod_status >= 0)
        .order_by(desc(vote_total), Statement.id)
        .all()
    )

    total_votes = sum(s.total_votes for s in statements)

    latest_consensus = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()

    key_info = None
    if discussion.created_by_key_id:
        key_record = db.session.get(PartnerApiKey, discussion.created_by_key_id)
        if key_record and key_record.partner_id == partner.id:
            key_info = {
                'prefix': key_record.key_prefix or '',
                'last4': key_record.key_last4 or '',
                'env': key_record.env,
                'status': key_record.status,
            }

    base = _get_base_url()
    can_edit = _member_can_manage_discussions(_current_partner_member(partner)) and not _is_admin_preview(partner)

    return render_template(
        'partner/portal/discussion_detail.html',
        partner=partner,
        discussion=discussion,
        statements=statements,
        total_votes=total_votes,
        latest_consensus=latest_consensus,
        key_info=key_info,
        embed_url=f"{base}/discussions/{discussion.id}/embed?ref={partner.slug}",
        consensus_url=f"{base}/discussions/{discussion.id}/{discussion.slug}/consensus?ref={partner.slug}",
        can_edit=can_edit,
        is_admin_preview=_is_admin_preview(partner),
        portal_page='detail',
    )


@partner_bp.route('/portal/discussions/<int:discussion_id>/embed-submissions', methods=['POST'])
@partner_login_required
def portal_set_embed_statement_submissions(discussion_id):
    """Enable/disable reader statement submissions directly from the embed."""
    partner = _current_partner()
    if not _member_can_manage_discussions(_current_partner_member(partner)):
        flash('You do not have permission to change embed submission settings.', 'warning')
        return redirect(url_for('partner.portal_discussion_detail', discussion_id=discussion_id))

    if _is_admin_preview(partner):
        flash('Admin preview mode: write actions are disabled.', 'warning')
        return redirect(url_for('partner.portal_discussion_detail', discussion_id=discussion_id))

    discussion = Discussion.query.filter(
        Discussion.id == discussion_id,
        _portal_discussion_belongs_clause(partner),
    ).first_or_404()

    if discussion.is_closed:
        flash('Reopen the discussion before changing embed submission settings.', 'warning')
        return redirect(url_for('partner.portal_discussion_detail', discussion_id=discussion_id))

    discussion.embed_statement_submissions_enabled = _form_bool('embed_statement_submissions_enabled')
    try:
        db.session.commit()
        state = 'enabled' if discussion.embed_statement_submissions_enabled else 'disabled'
        flash(f'Embed statement submissions {state}.', 'success')
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to update embed submission policy")
        flash('Could not update embed submission settings.', 'danger')

    return redirect(url_for('partner.portal_discussion_detail', discussion_id=discussion_id))


@partner_bp.route('/portal/discussions/<int:discussion_id>/statements/new', methods=['POST'])
@partner_login_required
def portal_add_statement(discussion_id):
    """Add a seed statement to a discussion directly from the portal UI."""
    partner = _current_partner()

    if not _member_can_manage_discussions(_current_partner_member(partner)):
        flash('You do not have permission to add statements.', 'error')
        return redirect(url_for('partner.portal_discussion_detail', discussion_id=discussion_id))

    if _is_admin_preview(partner):
        flash('Admin preview mode: write actions are disabled.', 'warning')
        return redirect(url_for('partner.portal_discussion_detail', discussion_id=discussion_id))

    discussion = Discussion.query.filter(
        Discussion.id == discussion_id,
        _portal_discussion_belongs_clause(partner),
    ).first_or_404()

    if discussion.is_closed:
        flash('This discussion is closed. Reopen it before adding statements.', 'warning')
        return redirect(url_for('partner.portal_discussion_detail', discussion_id=discussion_id))

    content = (request.form.get('content') or '').strip()
    stance = (request.form.get('stance') or '').strip()

    if not content:
        flash('Statement content is required.', 'error')
        return redirect(url_for('partner.portal_discussion_detail', discussion_id=discussion_id))
    if len(content) < 10:
        flash('Statement must be at least 10 characters.', 'error')
        return redirect(url_for('partner.portal_discussion_detail', discussion_id=discussion_id))
    if len(content) > 500:
        flash('Statement must be 500 characters or fewer.', 'error')
        return redirect(url_for('partner.portal_discussion_detail', discussion_id=discussion_id))
    if stance and stance not in ('pro', 'con', 'neutral'):
        stance = ''

    max_st = current_app.config.get('MAX_STATEMENTS_PER_DISCUSSION', 5000)
    current_count = Statement.query.filter_by(discussion_id=discussion_id, is_deleted=False).count()
    if current_count >= max_st:
        flash(f'This discussion has reached the maximum of {max_st} statements.', 'warning')
        return redirect(url_for('partner.portal_discussion_detail', discussion_id=discussion_id))

    existing = Statement.query.filter_by(
        discussion_id=discussion_id, content=content, is_deleted=False
    ).first()
    if existing:
        flash('An identical statement already exists in this discussion.', 'warning')
        return redirect(url_for('partner.portal_discussion_detail', discussion_id=discussion_id))

    stmt = Statement(
        discussion_id=discussion_id,
        content=content,
        seed_stance=stance or None,
        statement_type='claim',
        is_seed=True,
        mod_status=1,
        source='partner_provided',
    )
    db.session.add(stmt)
    if not discussion.has_native_statements:
        discussion.has_native_statements = True

    try:
        db.session.commit()
        invalidate_partner_snapshot_cache(discussion_id)
        flash('Statement added.', 'success')
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to add statement from portal")
        flash('Failed to add statement — please try again.', 'error')

    return redirect(url_for('partner.portal_discussion_detail', discussion_id=discussion_id))


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
        can_manage_keys=_member_can_manage_keys(current_member),
        domains=domains,
        keys=keys,
        has_verified_test_domain=has_verified_test_domain,
        has_test_key=has_test_key,
        has_live_key=has_live_key,
        base_url=_get_base_url(),
        portal_page='setup',
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
        can_manage_keys=_member_can_manage_keys(current_member),
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
    import csv
    from io import StringIO

    partner = _current_partner()
    if not _member_can_view_analytics(_current_partner_member(partner)):
        flash('You do not have permission to export analytics.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))
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
    # Reset explicit overrides when role changes; role defaults become source of truth.
    member.permissions_json = {}
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to update partner member role")
        flash('Could not update role.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))
    flash('Role updated.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/team/<int:member_id>/permissions', methods=['POST'])
@partner_login_required
def portal_update_member_permissions(member_id):
    partner = _current_partner()
    current_member = _current_partner_member(partner)
    if not _member_can_manage_team(current_member):
        flash('Only members with team permissions can update member permissions.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    member = PartnerMember.query.filter_by(id=member_id, partner_id=partner.id).first_or_404()
    if member.role == 'owner':
        flash('Owner permissions cannot be changed.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))
    if current_member and current_member.id == member.id and not request.form.get(PERM_TEAM_MANAGE):
        flash('You cannot remove your own team-management permission.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))

    member.permissions_json = _permissions_from_form()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to update member permissions")
        flash('Could not update member permissions.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))
    flash('Member permissions updated.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/domains/add', methods=['POST'])
@limiter.limit("10 per minute")
@partner_login_required
def portal_add_domain():
    partner = _current_partner()
    if not _member_can_manage_domains(_current_partner_member(partner)):
        flash('You do not have permission to manage domains.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))
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
    if not _member_can_manage_domains(_current_partner_member(partner)):
        flash('You do not have permission to manage domains.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))
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
    try:
        emit_partner_event(
            partner_id=partner.id,
            event_type=EVENT_DOMAIN_VERIFICATION_CHANGED,
            data=serialize_domain_payload(domain),
        )
    except Exception:
        current_app.logger.exception("Failed to emit domain.verification_changed on toggle")
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/domains/<int:domain_id>/remove', methods=['POST'])
@partner_login_required
def portal_remove_domain(domain_id):
    partner = _current_partner()
    if not _member_can_manage_domains(_current_partner_member(partner)):
        flash('You do not have permission to manage domains.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))
    domain = PartnerDomain.query.filter_by(id=domain_id, partner_id=partner.id).first_or_404()
    payload = serialize_domain_payload(domain)
    payload['deleted'] = True
    try:
        db.session.delete(domain)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to remove partner domain")
        flash('Could not remove domain.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))
    try:
        emit_partner_event(
            partner_id=partner.id,
            event_type=EVENT_DOMAIN_VERIFICATION_CHANGED,
            data=payload,
        )
    except Exception:
        current_app.logger.exception("Failed to emit domain.verification_changed on delete")
    flash('Domain removed.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/domains/<int:domain_id>/verify', methods=['POST'])
@partner_login_required
def portal_verify_domain(domain_id):
    partner = _current_partner()
    if not _member_can_manage_domains(_current_partner_member(partner)):
        flash('You do not have permission to manage domains.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))
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
        try:
            db.session.commit()
            flash('Domain verified successfully.', 'success')
        except Exception:
            db.session.rollback()
            current_app.logger.exception('portal_verify_domain: failed to save verified_at')
            flash('Domain check passed but could not be saved. Please try again.', 'danger')
    else:
        if details.get('error'):
            flash('Verification failed. DNS lookup error; check your DNS provider and try again.', 'danger')
        else:
            flash('Verification failed. TXT record not found yet. Check the expected value and try again.', 'danger')

    # Domain verification state can drive downstream allowlists.
    try:
        emit_partner_event(
            partner_id=partner.id,
            event_type=EVENT_DOMAIN_VERIFICATION_CHANGED,
            data=serialize_domain_payload(domain),
        )
    except Exception:
        current_app.logger.exception("Failed to emit domain.verification_changed webhook event")
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/webhooks/create', methods=['POST'])
@partner_login_required
def portal_create_webhook():
    partner = _current_partner()
    if not _member_can_manage_webhooks(_current_partner_member(partner)):
        flash('You do not have permission to manage webhooks.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))

    endpoint_url = (request.form.get('url') or '').strip()
    parsed = urlparse(endpoint_url)
    if not endpoint_url or parsed.scheme not in ('https',):
        flash('Webhook URL must be a valid HTTPS URL.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    event_types = [e for e in request.form.getlist('event_types') if e in ALL_PARTNER_EVENTS]
    if not event_types:
        flash('Select at least one webhook event type.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    try:
        plain_secret, encrypted_secret, secret_last4 = generate_webhook_secret()
    except Exception as exc:
        current_app.logger.exception("Failed to generate webhook secret")
        flash(f'Could not create webhook secret ({exc}). Check ENCRYPTION_KEY.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    endpoint = PartnerWebhookEndpoint(
        partner_id=partner.id,
        url=endpoint_url[:1000],
        status='active',
        event_types=event_types,
        encrypted_signing_secret=encrypted_secret,
        secret_last4=secret_last4,
    )
    try:
        db.session.add(endpoint)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to create partner webhook endpoint")
        flash('Could not create webhook endpoint.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    session['partner_new_webhook_secret'] = plain_secret
    flash('Webhook endpoint created. Copy the signing secret now; it will not be shown again.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/webhooks/<int:endpoint_id>/update', methods=['POST'])
@partner_login_required
def portal_update_webhook(endpoint_id):
    partner = _current_partner()
    if not _member_can_manage_webhooks(_current_partner_member(partner)):
        flash('You do not have permission to manage webhooks.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))

    endpoint = PartnerWebhookEndpoint.query.filter_by(id=endpoint_id, partner_id=partner.id).first_or_404()
    status = (request.form.get('status') or 'active').strip().lower()
    if status not in ('active', 'paused', 'disabled'):
        status = endpoint.status
    event_types = [e for e in request.form.getlist('event_types') if e in ALL_PARTNER_EVENTS]
    if not event_types:
        flash('Select at least one webhook event type.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    endpoint.status = status
    endpoint.event_types = event_types
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to update webhook endpoint")
        flash('Could not update webhook endpoint.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))
    flash('Webhook endpoint updated.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/webhooks/<int:endpoint_id>/rotate-secret', methods=['POST'])
@partner_login_required
def portal_rotate_webhook_secret(endpoint_id):
    partner = _current_partner()
    if not _member_can_manage_webhooks(_current_partner_member(partner)):
        flash('You do not have permission to manage webhooks.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))

    endpoint = PartnerWebhookEndpoint.query.filter_by(id=endpoint_id, partner_id=partner.id).first_or_404()
    try:
        plain_secret, encrypted_secret, secret_last4 = generate_webhook_secret()
    except Exception as exc:
        current_app.logger.exception("Failed to rotate webhook secret")
        flash(f'Could not rotate webhook secret ({exc}). Check ENCRYPTION_KEY.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    endpoint.encrypted_signing_secret = encrypted_secret
    endpoint.secret_last4 = secret_last4
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to save rotated webhook secret")
        flash('Could not rotate webhook secret.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))

    session['partner_new_webhook_secret'] = plain_secret
    flash('Webhook secret rotated. Copy the new secret now.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/webhooks/<int:endpoint_id>/delete', methods=['POST'])
@partner_login_required
def portal_delete_webhook(endpoint_id):
    partner = _current_partner()
    if not _member_can_manage_webhooks(_current_partner_member(partner)):
        flash('You do not have permission to manage webhooks.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))

    endpoint = PartnerWebhookEndpoint.query.filter_by(id=endpoint_id, partner_id=partner.id).first_or_404()
    try:
        PartnerWebhookDelivery.query.filter_by(endpoint_id=endpoint.id).delete(synchronize_session=False)
        db.session.delete(endpoint)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to delete webhook endpoint")
        flash('Could not delete webhook endpoint.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))
    flash('Webhook endpoint deleted.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/webhooks/<int:endpoint_id>/send-test', methods=['POST'])
@partner_login_required
def portal_send_test_webhook(endpoint_id):
    partner = _current_partner()
    if not _member_can_manage_webhooks(_current_partner_member(partner)):
        flash('You do not have permission to manage webhooks.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))

    endpoint = PartnerWebhookEndpoint.query.filter_by(id=endpoint_id, partner_id=partner.id).first_or_404()
    if endpoint.status != 'active':
        flash('Webhook endpoint must be active to send test events.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))

    try:
        delivery = send_test_delivery(endpoint)
    except Exception:
        current_app.logger.exception("Failed to send test webhook")
        flash('Could not send test webhook.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))
    if delivery.status == 'delivered':
        flash('Test webhook delivered successfully.', 'success')
    else:
        flash('Test webhook queued — delivery pending. Check your receiver logs shortly.', 'info')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/keys/create', methods=['POST'])
@partner_login_required
def portal_create_key():
    partner = _current_partner()
    if not _member_can_manage_keys(_current_partner_member(partner)):
        flash('Only owners and admins can create API keys.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))
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
    if not _member_can_manage_keys(_current_partner_member(partner)):
        flash('Only owners and admins can revoke API keys.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))
    key = PartnerApiKey.query.filter_by(id=key_id, partner_id=partner.id).first_or_404()
    key.status = 'revoked'
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to revoke API key")
        flash('An error occurred. Please try again.', 'danger')
        return redirect(url_for('partner.portal_dashboard'))
    try:
        emit_partner_event(
            partner_id=partner.id,
            event_type=EVENT_KEY_REVOKED,
            data=serialize_key_payload(key),
        )
    except Exception:
        current_app.logger.exception("Failed to emit key.revoked webhook event")
    flash('API key revoked.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/keys/<int:key_id>/rotate', methods=['POST'])
@partner_login_required
def portal_rotate_key(key_id):
    partner = _current_partner()
    if not _member_can_manage_keys(_current_partner_member(partner)):
        flash('Only owners and admins can rotate API keys.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))
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
    try:
        emit_partner_event(
            partner_id=partner.id,
            event_type=EVENT_KEY_REVOKED,
            data=serialize_key_payload(key),
        )
    except Exception:
        current_app.logger.exception("Failed to emit key.revoked for rotated key")

    session['partner_new_key'] = full_key
    flash('API key rotated. Copy the new key now; it will not be shown again.', 'success')
    return redirect(url_for('partner.portal_dashboard'))


@partner_bp.route('/portal/billing/start', methods=['POST'])
@partner_login_required
def portal_start_billing():
    partner = _current_partner()
    if not _member_can_manage_billing(_current_partner_member(partner)):
        flash('You do not have permission to manage billing.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))
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
    if not _member_can_manage_billing(_current_partner_member(partner)):
        flash('You do not have permission to manage billing.', 'warning')
        return redirect(url_for('partner.portal_dashboard'))
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
