# Contributing to Earthward Foundry

This repository is the operating scaffold for Earthward's agent fleet. It is
proprietary (see `LICENSE`) — this guide is for authorized collaborators.

## The four non-negotiable rules

Every change — agent prompt, service, or schema — must uphold these, with
no exceptions:

1. **No agent self-certifies its own output.** Every irreversible or
   safety/quality/spend-relevant action requires a named human sign-off.
2. **No agent hides a failure to look complete.** Blocked, failed, or
   uncertain results are reported as such, never smoothed over.
3. **No agent invents a standard, spec, or certification.** If no real
   standard backs a recommendation, the agent says so and routes to a human.
4. **Every escalation names who it goes to.** Never "a human" — a specific
   role, callsign, or ID.

If a proposed change weakens any of these (e.g. moves an enforcement check
from code into a prompt-only instruction, or removes a human-only gate),
it will be rejected regardless of how it's justified.

## Adding or editing an agent file (`agents/**/*.md`)

Every agent file follows the same four-part structure so it drops directly
into a system prompt:

- `JOB` — what the agent does, precisely.
- `NEVER` — the hard boundaries it does not cross.
- `ESCALATE` — the named-human handoff trigger(s).
- `OUTPUT` — the structured format it always responds in.

Keep new agent files inside the correct house folder (`agents/<house>/`) and
register them in `agents/manifest.json`.

## Adding or editing a runnable service (`services/**`)

- **Enforcement belongs in code, not in a docstring or prompt.** Follow the
  pattern in `services/traceability/service.py` and
  `services/rescue/incident_log.py`: hard rules are checked in the function
  that mutates state, and every rejection raises a specific, named exception
  — never a silent no-op.
- **Every new module needs tests before merge.** Match the existing style:
  plain `test_*` functions using `assert`, an `ALL_TESTS` list, and a
  `__main__` block that runs them and exits non-zero on failure (see
  `services/traceability/tests/test_traceability.py`). This lets any test
  file run standalone (`python3 tests/test_x.py`) as well as under CI.
- **HTTP APIs require authentication.** Any new Flask app must call
  `require_api_key(app, "<SERVICE>_API_KEY")` from `api_auth.py` before
  registering routes — copy the pattern from `services/rescue/api.py` or
  `services/traceability/api.py`. Never ship an endpoint that trusts a
  client-supplied `source` field as identity.
- **Never hardcode `debug=True`.** Read it from an environment variable,
  default to `False`, and refuse to start if debug mode is requested on a
  non-localhost bind address (see the `__main__` block in either `api.py`
  for the exact guard).
- **Pin dependencies exactly** in that service's `requirements.txt` (e.g.
  `flask==3.1.3`, not `flask>=3.0`) so builds are reproducible.

## Before opening a PR

1. Run every test file for every service you touched:
   ```bash
   cd services/<service> && for f in tests/test_*.py; do python3 "$f"; done
   ```
2. Run the linter from the repo root: `ruff check .`
3. If you touched a Dockerfile, confirm it still builds:
   `docker build -t <service> services/<service>`
4. CI (`.github/workflows/ci.yml`) runs all of the above automatically on
   every push and PR to `main` — a red CI run blocks merge.

## Reporting a vulnerability

See `SECURITY.md` — do not open a public issue for a security problem.
