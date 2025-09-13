"""
Webhook security utilities for HMAC signature verification and validation.
"""
import hashlib
import hmac
import time
from functools import wraps
from flask import request, jsonify, current_app, abort


def generate_signature(payload, secret):
    """Generate HMAC signature for webhook payload"""
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    elif isinstance(payload, dict):
        import json
        payload = json.dumps(payload, sort_keys=True).encode('utf-8')
    
    signature = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return f"sha256={signature}"


def verify_webhook_signature(payload, signature, secret):
    """Verify webhook HMAC signature"""
    if not signature:
        return False
    
    # Remove 'sha256=' prefix if present
    if signature.startswith('sha256='):
        signature = signature[7:]
    
    expected_signature = generate_signature(payload, secret)
    if expected_signature.startswith('sha256='):
        expected_signature = expected_signature[7:]
    
    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(signature, expected_signature)


def webhook_required(f):
    """Decorator to require valid webhook signature for protected endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get the raw payload
        payload = request.get_data()
        
        # Get signature from headers
        signature = request.headers.get('X-Signature-256') or request.headers.get('X-Hub-Signature-256')
        
        # Get webhook secret from config
        webhook_secret = current_app.config.get('WEBHOOK_SECRET')
        
        if not webhook_secret:
            current_app.logger.error("WEBHOOK_SECRET not configured")
            abort(500)
        
        # For development, allow bypassing signature verification
        if current_app.config.get('DEBUG') and not signature:
            current_app.logger.warning("Webhook signature verification bypassed in development mode")
            return f(*args, **kwargs)
        
        # Verify signature
        if not verify_webhook_signature(payload, signature, webhook_secret):
            current_app.logger.warning(f"Invalid webhook signature from {request.remote_addr}")
            abort(401)
        
        return f(*args, **kwargs)
    
    return decorated_function


def validate_webhook_timestamp(timestamp_header=None, tolerance=300):
    """
    Validate webhook timestamp to prevent replay attacks
    
    Args:
        timestamp_header: The header name containing timestamp (e.g., 'X-Timestamp')
        tolerance: Maximum age of webhook in seconds (default: 5 minutes)
    
    Returns:
        bool: True if timestamp is valid, False otherwise
    """
    if not timestamp_header:
        return True  # Skip validation if no timestamp header specified
    
    timestamp = request.headers.get(timestamp_header)
    if not timestamp:
        return False
    
    try:
        webhook_time = int(timestamp)
        current_time = int(time.time())
        
        # Check if webhook is too old or from the future
        if abs(current_time - webhook_time) > tolerance:
            current_app.logger.warning(f"Webhook timestamp out of tolerance: {webhook_time} vs {current_time}")
            return False
        
        return True
    except (ValueError, TypeError):
        current_app.logger.warning(f"Invalid webhook timestamp format: {timestamp}")
        return False


def webhook_with_timestamp(timestamp_header='X-Timestamp', tolerance=300):
    """Decorator to require valid webhook signature and timestamp"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # First check timestamp
            if not validate_webhook_timestamp(timestamp_header, tolerance):
                current_app.logger.warning(f"Invalid webhook timestamp from {request.remote_addr}")
                abort(401)
            
            # Then check signature
            return webhook_required(f)(*args, **kwargs)
        
        return decorated_function
    return decorator