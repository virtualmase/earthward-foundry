"""
API-key authentication for the Flask HTTP layer — zero external dependencies.

Why this exists: the `source` field on a request body (agent name or human
ID) records *provenance* for the append-only ledger. It is operator-supplied
and trivially spoofable — it is not proof of identity and must never be
treated as one. Authentication has to happen at the transport layer instead,
before a request body is ever parsed.

Usage (see api.py):
    from api_auth import require_api_key
    require_api_key(app, "RESCUE_API_KEY")

Set RESCUE_API_KEY in the environment (see .env.example) to require a
matching `Authorization: Bearer <key>` header on every request except the
exempt liveness/discovery routes. Leaving the variable unset refuses to
serve requests unless ALLOW_UNAUTHENTICATED=true is explicitly set — that
escape hatch exists only for local demos against 127.0.0.1 and must never
be set in a deployed environment.

A minimal in-memory fixed-window rate limiter rides along for defense in
depth against credential-stuffing and DoS. It is per-process, not
distributed-safe, and intentionally simple — swap for a real rate limiter
(e.g. an API gateway) before scaling past one instance.
"""
from __future__ import annotations

import hmac
import os
import time
from collections import defaultdict, deque

from flask import jsonify, request

EXEMPT_PATHS = frozenset({"/health", "/openapi.yaml"})

_RATE_WINDOW_SECONDS = 60
_request_log: dict[str, deque] = defaultdict(deque)


def _rate_limited(client_id: str, limit_per_minute: int) -> bool:
    if limit_per_minute <= 0:
        return False
    now = time.monotonic()
    bucket = _request_log[client_id]
    while bucket and now - bucket[0] > _RATE_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= limit_per_minute:
        return True
    bucket.append(now)
    return False


def require_api_key(app, env_var: str):
    """Register a before_request hook enforcing bearer-token auth + rate limiting."""

    @app.before_request
    def _check_api_key():
        if request.path in EXEMPT_PATHS:
            return None

        limit = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "120"))
        client_id = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
        if _rate_limited(client_id, limit):
            return jsonify({
                "error": "RateLimited",
                "message": "Too many requests. Slow down and retry shortly.",
            }), 429

        api_key = os.environ.get(env_var, "")
        if not api_key:
            if os.environ.get("ALLOW_UNAUTHENTICATED", "false").lower() == "true":
                return None
            return jsonify({
                "error": "ServerMisconfigured",
                "message": (
                    f"{env_var} is not set. Refusing to serve requests without "
                    f"authentication. Set {env_var} in your environment, or set "
                    "ALLOW_UNAUTHENTICATED=true for local demos only."
                ),
            }), 500

        header = request.headers.get("Authorization", "")
        supplied = header[7:] if header.startswith("Bearer ") else ""
        if not supplied or not hmac.compare_digest(supplied, api_key):
            return jsonify({"error": "Unauthorized", "message": "Missing or invalid API key."}), 401
        return None

    return app
