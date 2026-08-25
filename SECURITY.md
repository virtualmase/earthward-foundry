# Security Policy

## Reporting a vulnerability

Do not open a public GitHub issue for a security problem. Instead, email
**virtualmase@gmail.com** with:

- A description of the issue and its potential impact.
- Steps to reproduce (a minimal request/script is ideal).
- Which service and file/line are affected, if known.

You should receive an acknowledgment within a few days. Please allow time
for a fix before any public disclosure.

## Security model

### Transport-layer authentication

Both HTTP services (`services/traceability/api.py`, `services/rescue/api.py`)
require a bearer-token API key on every request except `GET /health` and
`GET /openapi.yaml`, enforced in `api_auth.py` via a `before_request` hook:

- Set `TRACEABILITY_API_KEY` / `RESCUE_API_KEY` in the environment (never
  commit these — see `.env.example` and `.gitignore`).
- Requests without a valid `Authorization: Bearer <key>` header receive
  `401 Unauthorized`. Keys are compared with `hmac.compare_digest` to avoid
  timing side-channels.
- If no key is configured, the service refuses all non-exempt requests with
  `500 ServerMisconfigured` rather than silently accepting unauthenticated
  traffic. The only way to serve unauthenticated requests is to explicitly
  set `ALLOW_UNAUTHENTICATED=true` — intended only for local demos against
  `127.0.0.1`, never for a deployed instance.
- A minimal in-memory rate limiter (`RATE_LIMIT_PER_MINUTE`, default 120/min
  per client) is applied ahead of the auth check as defense in depth. It is
  per-process and not distributed-safe — put a real rate limiter or gateway
  in front before scaling past one instance.

**Important:** the `source` object in request bodies (`{"type": "agent"|"human", "id": "..."}`)
records *provenance* for the append-only ledger, not identity. It is
client-supplied and must never be treated as authentication. The four
non-negotiable fleet rules (see `README.md`) are enforced independently of
this field's contents by `service.py` / `incident_log.py`.

### Debug mode

Both `api.py` entry points read debug mode from an environment variable
(`TRACEABILITY_API_DEBUG` / `RESCUE_API_DEBUG`, default `false`) and refuse
to start with debug enabled unless the bind host is `127.0.0.1` or
`localhost`. Flask's debug mode exposes the Werkzeug interactive debugger,
which allows arbitrary code execution to anyone who can reach it — it must
never be enabled on a host or port reachable from outside the machine
running it.

### Secrets

- `.env` is git-ignored; only `.env.example` (with placeholder values) is
  committed.
- API keys, `ANTHROPIC_API_KEY`, and any future credentials must be supplied
  via environment variables or your deployment platform's secret manager —
  never hardcoded or committed.

### Dependencies

Dependencies are pinned to exact versions in each service's
`requirements.txt` for reproducible builds. CI (`.github/workflows/ci.yml`)
runs the full test suite across supported Python versions on every push and
PR to `main`.

### Data integrity

Both datastores (`services/traceability`, `services/rescue`) are append-only
SQLite stores: no code path updates or deletes an existing row, and every
correction is a new event that references what it corrects. This is
enforced in `service.py` / `incident_log.py`, not left to caller discipline.
