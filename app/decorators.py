"""
Shared Decorators

Common decorators used across multiple blueprints.
"""

from functools import wraps
from flask import flash, redirect, url_for, request, jsonify
from flask_login import current_user


def admin_required(f):
    """
    Decorator to require admin access.

    Should be used with @login_required:
        @route('/admin')
        @login_required
        @admin_required
        def admin_page():
            ...

    Handles both HTML and JSON responses based on request type.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            # Check if this is an API/AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                return jsonify({'error': 'Admin access required'}), 403
            flash('Admin access required.', 'error')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function
