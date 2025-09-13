"""
Webhook security utilities for HMAC signature verification and validation.
"""
import hashlib
import hmac
import time
from functools import wraps
from flask import request, jsonify, current_app, abort


def generate_signature(payload, secret, timestamp=None):
    """Generate HMAC signature for webhook payload with optional timestamp binding"""
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    elif isinstance(payload, dict):
        import json
        payload = json.dumps(payload, sort_keys=True).encode('utf-8')
    
    # Bind timestamp to prevent replay attacks
    if timestamp:
        message = f"{timestamp}.{payload.decode('utf-8')}"
        payload = message.encode('utf-8')
    
    signature = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return f"sha256={signature}"


def verify_webhook_signature(payload, signature, secret, timestamp=None):
    """Verify webhook HMAC signature with optional timestamp binding"""
    if not signature:
        return False
    
    # Remove 'sha256=' prefix if present
    if signature.startswith('sha256='):
        signature = signature[7:]
    
    expected_signature = generate_signature(payload, secret, timestamp)
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
    """Decorator to require valid webhook signature bound to timestamp"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get timestamp and payload
            timestamp = request.headers.get(timestamp_header)
            payload = request.get_data()
            signature = request.headers.get('X-Signature-256') or request.headers.get('X-Hub-Signature-256')
            
            # Get webhook secret
            webhook_secret = current_app.config.get('WEBHOOK_SECRET')
            if not webhook_secret:
                current_app.logger.error("WEBHOOK_SECRET not configured")
                abort(500)
            
            # For development, allow bypassing if no headers provided
            if current_app.config.get('DEBUG') and not (signature and timestamp):
                current_app.logger.warning("Webhook security bypassed in development mode")
                return f(*args, **kwargs)
            
            # Validate timestamp
            if not timestamp:
                current_app.logger.warning(f"Missing webhook timestamp from {request.remote_addr}")
                abort(401)
            
            if not validate_webhook_timestamp(timestamp_header, tolerance):
                current_app.logger.warning(f"Invalid webhook timestamp from {request.remote_addr}")
                abort(401)
            
            # Check for replay attacks using Redis cache
            if not check_replay_protection(timestamp, payload):
                current_app.logger.warning(f"Replay attack detected from {request.remote_addr}")
                abort(401)
            
            # Verify signature with timestamp bound
            if not verify_webhook_signature(payload, signature, webhook_secret, timestamp):
                current_app.logger.warning(f"Invalid webhook signature from {request.remote_addr}")
                abort(401)
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


def check_replay_protection(timestamp, payload):
    """Check for replay attacks using Redis cache"""
    try:
        from flask import current_app
        import hashlib
        
        # Create unique request identifier
        request_id = hashlib.sha256(f"{timestamp}.{payload.decode('utf-8') if isinstance(payload, bytes) else payload}".encode()).hexdigest()
        
        # Try to connect to Redis for replay protection
        redis_url = current_app.config.get('REDIS_URL')
        if redis_url and not redis_url.startswith('memory://'):
            try:
                import redis
                r = redis.from_url(redis_url)
                
                # Use SETNX to atomically check and set
                # Returns True if key didn't exist (first time seeing this request)
                # Returns False if key already exists (replay attack)
                is_new_request = r.set(f"webhook_replay:{request_id}", "1", ex=300, nx=True)
                return bool(is_new_request)
                
            except Exception as redis_error:
                current_app.logger.error(f"Redis replay protection failed: {redis_error}")
                # In production, fail closed (reject request)
                if current_app.config.get('FLASK_ENV') == 'production':
                    return False
                # In development, allow through with warning
                current_app.logger.warning("Replay protection disabled - Redis unavailable")
                return True
        else:
            # No Redis available for replay protection
            current_app.logger.warning("Replay protection disabled - no Redis configured")
            return True
            
    except Exception as e:
        current_app.logger.error(f"Replay protection check failed: {e}")
        # Fail closed in production
        if current_app.config.get('FLASK_ENV') == 'production':
            return False
        return True