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

    # Get a service token from Core
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
