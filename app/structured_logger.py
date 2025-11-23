"""
Structured JSON Logger with Correlation IDs for HiveMatrix

This module provides JSON-formatted logging with automatic correlation ID tracking
for distributed request tracing across services.

Usage in app/__init__.py:
    from app.structured_logger import setup_structured_logging
    setup_structured_logging(app)

Usage in routes:
    from flask import g
    app.logger.info('Company created', extra={
        'company_id': 123,
        'account_number': '12345',
        'user_id': g.user.get('sub') if hasattr(g, 'user') else None
    })
"""

import logging
import json
import uuid
from datetime import datetime
from flask import request, g, has_request_context


class JSONFormatter(logging.Formatter):
    """
    Formats log records as JSON with correlation IDs and structured data.
    """

    def format(self, record):
        log_data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }

        # Add correlation ID if available
        if has_request_context():
            if hasattr(g, 'correlation_id'):
                log_data['correlation_id'] = g.correlation_id
            if hasattr(g, 'user') and g.user:
                log_data['user_id'] = g.user.get('sub')
                log_data['username'] = g.user.get('preferred_username')

        # Add any extra fields from extra parameter
        if hasattr(record, 'extra_data'):
            log_data.update(record.extra_data)

        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_data)


class StructuredLoggerAdapter(logging.LoggerAdapter):
    """
    Adapter that adds extra data to log records.
    """

    def process(self, msg, kwargs):
        # Extract extra dict and store it in the record
        extra = kwargs.get('extra', {})
        kwargs['extra'] = {'extra_data': extra}
        return msg, kwargs


def setup_structured_logging(app, enable_json=True):
    """
    Configure structured JSON logging for a Flask application.

    Args:
        app: Flask application instance
        enable_json: If True, use JSON formatter. If False, use standard text logging.

    This function:
    1. Configures JSON log formatting
    2. Sets up correlation ID middleware
    3. Configures log level from environment
    """

    # Configure log handler
    handler = logging.StreamHandler()

    if enable_json:
        handler.setFormatter(JSONFormatter())
    else:
        # Standard text format for development
        handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        ))

    # Remove existing handlers and add ours
    app.logger.handlers.clear()
    app.logger.addHandler(handler)

    # Add correlation ID middleware
    @app.before_request
    def set_correlation_id():
        """Generate or extract correlation ID for request tracing."""
        # Check if correlation ID was passed from another service
        g.correlation_id = request.headers.get('X-Correlation-ID', str(uuid.uuid4()))

    @app.after_request
    def add_correlation_id_header(response):
        """Add correlation ID to response headers for client tracking."""
        if hasattr(g, 'correlation_id'):
            response.headers['X-Correlation-ID'] = g.correlation_id
        return response

    # Log service startup with structured format
    app.logger.info(f"{app.config.get('SERVICE_NAME', 'unknown')} service initialized with structured logging")

    return app
