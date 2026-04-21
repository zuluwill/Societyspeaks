# app/settings/api_keys.py
"""
User API Key Management (Phase 4.1)

Allows users to add/manage their own LLM API keys
for optional AI features
"""
from flask import render_template, redirect, url_for, flash, request, Blueprint
from flask_login import login_required, current_user
from app import db, limiter
from app.models import UserAPIKey
from app.lib.llm_utils import encrypt_api_key, validate_api_key
from datetime import datetime
from app.lib.time import utcnow_naive
import logging
from flask_babel import gettext as _

api_keys_bp = Blueprint('api_keys', __name__)
logger = logging.getLogger(__name__)


@api_keys_bp.route('/settings/api-keys')
@login_required
def list_api_keys():
    """
    List user's API keys (masked for security)
    """
    keys = UserAPIKey.query.filter_by(user_id=current_user.id).all()
    
    return render_template('settings/api_keys.html', keys=keys)


@api_keys_bp.route('/settings/api-keys/add', methods=['GET', 'POST'])
@login_required
@limiter.limit("5 per hour")
def add_api_key():
    """
    Add a new API key
    Validates the key before storing
    """
    if request.method == 'POST':
        provider = request.form.get('provider')
        api_key = request.form.get('api_key')
        
        if not provider or not api_key:
            flash(_("Provider and API key are required"), "danger")
            return render_template('settings/add_api_key.html')
        
        if provider not in ['openai', 'anthropic', 'mistral']:
            flash(_("Invalid provider"), "danger")
            return render_template('settings/add_api_key.html')
        
        # Check if user already has a key for this provider
        existing = UserAPIKey.query.filter_by(
            user_id=current_user.id,
            provider=provider
        ).first()
        
        if existing:
            flash(_('You already have an API key for %(provider)s. Delete the old one first.', provider=provider), "warning")
            return redirect(url_for('api_keys.list_api_keys'))
        
        # Validate the API key
        logger.info(f"Validating {provider} API key for user {current_user.id}")
        is_valid, message = validate_api_key(provider, api_key)
        
        if not is_valid:
            flash(_('API key validation failed: %(message)s', message=message), "danger")
            return render_template('settings/add_api_key.html', 
                                 provider=provider)
        
        # Encrypt and store
        try:
            encrypted_key = encrypt_api_key(api_key)
            
            new_key = UserAPIKey(
                user_id=current_user.id,
                provider=provider,
                encrypted_api_key=encrypted_key,
                is_active=True,
                last_validated=utcnow_naive()
            )
            
            db.session.add(new_key)
            db.session.commit()
            
            flash(f"{provider.title()} API key added successfully! You can now use AI features.", "success")
            return redirect(url_for('api_keys.list_api_keys'))
        
        except Exception as e:
            logger.error(f"Error storing API key: {e}")
            flash(_("Error storing API key. Please try again."), "danger")
            return render_template('settings/add_api_key.html')
    
    return render_template('settings/add_api_key.html')


@api_keys_bp.route('/settings/api-keys/<int:key_id>/delete', methods=['POST'])
@login_required
def delete_api_key(key_id):
    """
    Delete an API key
    """
    api_key = db.get_or_404(UserAPIKey, key_id)
    
    # Check ownership
    if api_key.user_id != current_user.id:
        flash(_("You can only delete your own API keys"), "danger")
        return redirect(url_for('api_keys.list_api_keys'))
    
    provider = api_key.provider
    db.session.delete(api_key)
    db.session.commit()
    
    flash(f"{provider.title()} API key deleted", "success")
    return redirect(url_for('api_keys.list_api_keys'))


@api_keys_bp.route('/settings/api-keys/<int:key_id>/toggle', methods=['POST'])
@login_required
def toggle_api_key(key_id):
    """
    Activate/deactivate an API key
    """
    api_key = db.get_or_404(UserAPIKey, key_id)
    
    # Check ownership
    if api_key.user_id != current_user.id:
        flash(_("You can only modify your own API keys"), "danger")
        return redirect(url_for('api_keys.list_api_keys'))
    
    api_key.is_active = not api_key.is_active
    db.session.commit()
    
    status = "activated" if api_key.is_active else "deactivated"
    flash(_('API key %(status)s', status=status), "success")
    return redirect(url_for('api_keys.list_api_keys'))


@api_keys_bp.route('/settings/api-keys/<int:key_id>/revalidate', methods=['POST'])
@login_required
@limiter.limit("10 per hour")
def revalidate_api_key(key_id):
    """
    Re-validate an API key to check if it's still working
    """
    api_key_record = db.get_or_404(UserAPIKey, key_id)
    
    # Check ownership
    if api_key_record.user_id != current_user.id:
        flash(_("You can only validate your own API keys"), "danger")
        return redirect(url_for('api_keys.list_api_keys'))
    
    try:
        from app.lib.llm_utils import decrypt_api_key
        
        # Decrypt and validate
        plain_key = decrypt_api_key(api_key_record.encrypted_api_key)
        is_valid, message = validate_api_key(api_key_record.provider, plain_key)
        
        if is_valid:
            api_key_record.last_validated = utcnow_naive()
            api_key_record.is_active = True
            db.session.commit()
            flash(_("API key is valid and active"), "success")
        else:
            api_key_record.is_active = False
            db.session.commit()
            flash(_('API key is invalid: %(message)s', message=message), "danger")
    
    except Exception as e:
        logger.error(f"Error revalidating API key: {e}")
        flash(_("Error validating API key"), "danger")
    
    return redirect(url_for('api_keys.list_api_keys'))


@api_keys_bp.route('/api/user/llm-status')
@login_required
def llm_status():
    """
    API endpoint to check if user has LLM features enabled
    Used by frontend to show/hide AI features
    """
    from flask import jsonify
    
    has_active_key = UserAPIKey.query.filter_by(
        user_id=current_user.id,
        is_active=True
    ).first() is not None
    
    providers = []
    if has_active_key:
        providers = [
            key.provider for key in UserAPIKey.query.filter_by(
                user_id=current_user.id,
                is_active=True
            ).all()
        ]
    
    return jsonify({
        'llm_enabled': has_active_key,
        'providers': providers
    })

