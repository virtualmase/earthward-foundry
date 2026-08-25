"""
Structured request/response/error logging for the Flask HTTP layer —
stdlib only, container-friendly (writes to stdout, one line per event).

Mirrors the fleet's rule that no failure is ever hidden: any unhandled
exception is logged with its full traceback and reported to the caller as
an explicit 500, never swallowed into a bare Flask default error page with
no record of what happened.
"""
from __future__ import annotations

import logging
import os
import sys
import time

from flask import g, jsonify, request

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("earthward")


def configure_logging(app, service_name: str):
    """Attach request/response/error logging hooks to a Flask app."""

    @app.before_request
    def _start_timer():
        g._request_start = time.monotonic()

    @app.after_request
    def _log_response(response):
        duration_ms = (time.monotonic() - getattr(g, "_request_start", time.monotonic())) * 1000
        logger.info(
            "%s method=%s path=%s status=%d duration_ms=%.1f remote=%s",
            service_name,
            request.method,
            request.path,
            response.status_code,
            duration_ms,
            request.headers.get("X-Forwarded-For", request.remote_addr or "unknown"),
        )
        return response

    @app.errorhandler(Exception)
    def _log_unhandled(exc):
        logger.exception(
            "%s unhandled_exception method=%s path=%s", service_name, request.method, request.path
        )
        return jsonify({
            "error": "InternalServerError",
            "message": "An unexpected error occurred and has been logged. This is not a "
                       "silent failure — it will be visible in service logs.",
        }), 500

    return app
