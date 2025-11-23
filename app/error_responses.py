"""
RFC 7807 Problem Details for HTTP APIs
Provides standardized error response formatting across the application.
"""
from flask import jsonify, request
from werkzeug.http import HTTP_STATUS_CODES


def problem_detail(status, title=None, detail=None, type_suffix=None, instance=None, **extra):
    """
    Create an RFC 7807 Problem Details response.

    Args:
        status: HTTP status code
        title: Short human-readable summary (defaults to HTTP status phrase)
        detail: Human-readable explanation specific to this occurrence
        type_suffix: Suffix for the problem type URI (e.g., "invalid-token")
        instance: URI reference identifying the specific occurrence
        **extra: Additional problem-specific fields

    Returns:
        Flask JSON response with appropriate status code
    """
    # Default title to HTTP status phrase
    if title is None:
        title = HTTP_STATUS_CODES.get(status, "Error")

    # Build problem details object
    problem = {
        "type": f"about:blank#{type_suffix}" if type_suffix else "about:blank",
        "title": title,
        "status": status
    }

    if detail:
        problem["detail"] = detail

    if instance:
        problem["instance"] = instance
    elif request:
        problem["instance"] = request.path

    # Add any extra fields
    problem.update(extra)

    response = jsonify(problem)
    response.status_code = status
    response.headers["Content-Type"] = "application/problem+json"

    return response


def bad_request(detail=None, **extra):
    """400 Bad Request"""
    return problem_detail(
        400,
        title="Bad Request",
        detail=detail,
        type_suffix="bad-request",
        **extra
    )


def unauthorized(detail=None, **extra):
    """401 Unauthorized"""
    return problem_detail(
        401,
        title="Unauthorized",
        detail=detail or "Authentication required",
        type_suffix="unauthorized",
        **extra
    )


def forbidden(detail=None, **extra):
    """403 Forbidden"""
    return problem_detail(
        403,
        title="Forbidden",
        detail=detail or "You don't have permission to access this resource",
        type_suffix="forbidden",
        **extra
    )


def not_found(detail=None, resource=None, **extra):
    """404 Not Found"""
    if resource:
        detail = f"{resource} not found"
    return problem_detail(
        404,
        title="Not Found",
        detail=detail or "The requested resource was not found",
        type_suffix="not-found",
        **extra
    )


def conflict(detail=None, **extra):
    """409 Conflict"""
    return problem_detail(
        409,
        title="Conflict",
        detail=detail,
        type_suffix="conflict",
        **extra
    )


def unprocessable_entity(detail=None, errors=None, **extra):
    """422 Unprocessable Entity"""
    if errors:
        extra["errors"] = errors
    return problem_detail(
        422,
        title="Unprocessable Entity",
        detail=detail or "The request was well-formed but contains semantic errors",
        type_suffix="unprocessable-entity",
        **extra
    )


def rate_limit_exceeded(detail=None, retry_after=None, **extra):
    """429 Too Many Requests"""
    if retry_after:
        extra["retry_after"] = retry_after
    response = problem_detail(
        429,
        title="Too Many Requests",
        detail=detail or "Rate limit exceeded",
        type_suffix="rate-limit-exceeded",
        **extra
    )
    if retry_after:
        response.headers["Retry-After"] = str(retry_after)
    return response


def internal_server_error(detail=None, **extra):
    """500 Internal Server Error"""
    return problem_detail(
        500,
        title="Internal Server Error",
        detail=detail or "An unexpected error occurred",
        type_suffix="internal-server-error",
        **extra
    )


def service_unavailable(detail=None, retry_after=None, **extra):
    """503 Service Unavailable"""
    if retry_after:
        extra["retry_after"] = retry_after
    response = problem_detail(
        503,
        title="Service Unavailable",
        detail=detail or "The service is temporarily unavailable",
        type_suffix="service-unavailable",
        **extra
    )
    if retry_after:
        response.headers["Retry-After"] = str(retry_after)
    return response
