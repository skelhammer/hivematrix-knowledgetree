"""
Per-user rate limiting key function for Flask-Limiter.

This module provides a key function that identifies users by their JWT token
for more accurate rate limiting. Falls back to IP address for unauthenticated requests.
"""
from flask import g, has_request_context
from flask_limiter.util import get_remote_address


def get_user_id_or_ip():
    """
    Get rate limit key based on authenticated user or IP address.

    Priority:
    1. User ID from JWT token (g.user['sub'])
    2. IP address (for unauthenticated requests)

    This ensures:
    - Authenticated users are limited per-user (prevents abuse from shared IPs)
    - Unauthenticated requests are limited per-IP (prevents brute force)

    Returns:
        str: Rate limit key (user ID or IP address)
    """
    if not has_request_context():
        return "127.0.0.1"  # Default for background tasks

    # Try to get user ID from JWT token in Flask g object
    if hasattr(g, 'user') and g.user and isinstance(g.user, dict):
        user_id = g.user.get('sub')
        if user_id:
            return f"user:{user_id}"

    # Fall back to IP address for unauthenticated requests
    return f"ip:{get_remote_address()}"
