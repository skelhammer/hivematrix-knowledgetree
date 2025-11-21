"""
Service-to-Service Authentication Helper for HiveMatrix

Add this to each service that needs to call other services.
Usage:
    from app.service_client import call_service

    response = call_service('codex', '/api/companies')
    # or
    response = call_service('codex', '/api/search', method='POST', json={'query': 'test'})
"""

import requests
from flask import current_app
import time
import jwt

# Token cache: {target_service: {'token': str, 'expires_at': float}}
_token_cache = {}

def _get_cached_token(service_name):
    """Get cached token if valid, otherwise None."""
    if service_name not in _token_cache:
        return None

    cache_entry = _token_cache[service_name]
    # Check if token expires in next 60 seconds
    if cache_entry['expires_at'] - time.time() < 60:
        return None

    return cache_entry['token']

def _cache_token(service_name, token):
    """Cache token with expiration time."""
    try:
        # Decode token to get expiration (without verification since we trust Core)
        decoded = jwt.decode(token, options={"verify_signature": False})
        expires_at = decoded.get('exp', time.time() + 300)  # Default 5 min if no exp
    except Exception:
        # If we can't decode, cache for 5 minutes
        expires_at = time.time() + 300

    _token_cache[service_name] = {
        'token': token,
        'expires_at': expires_at
    }

def call_service(service_name, path, method='GET', **kwargs):
    """
    Makes an authenticated request to another HiveMatrix service.
    This uses Core to mint a service token for authentication.

    Args:
        service_name: The target service name (e.g., 'codex', 'template')
        path: The path to call (e.g., '/api/data')
        method: HTTP method (default: 'GET')
        **kwargs: Additional arguments to pass to requests.request()

    Returns:
        requests.Response object

    Example:
        response = call_service('codex', '/api/companies')
        companies = response.json()
    """
    # Get the service URL from configuration
    services = current_app.config.get('SERVICES', {})
    if service_name not in services:
        raise ValueError(f"Service '{service_name}' not found in configuration")

    service_url = services[service_name]['url']

    # Check for cached token first
    token = _get_cached_token(service_name)

    if not token:
        # Get a new service token from Core
        core_url = current_app.config.get('CORE_SERVICE_URL')
        calling_service = current_app.config.get('SERVICE_NAME', 'unknown')

        token_response = requests.post(
            f"{core_url}/service-token",
            json={
                'calling_service': calling_service,
                'target_service': service_name
            },
            timeout=5
        )

        if token_response.status_code != 200:
            raise Exception(f"Failed to get service token from Core: {token_response.text}")

        token = token_response.json()['token']

        # Cache the token
        _cache_token(service_name, token)

    # Make the request with auth header
    url = f"{service_url}{path}"
    headers = kwargs.pop('headers', {})
    headers['Authorization'] = f'Bearer {token}'

    response = requests.request(
        method=method,
        url=url,
        headers=headers,
        **kwargs
    )

    return response
