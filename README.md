# Earthward Foundry & Works — Agent Fleet Repository

[![CI](https://github.com/virtualmase/earthward-foundry/actions/workflows/ci.yml/badge.svg)](https://github.com/virtualmase/earthward-foundry/actions/workflows/ci.yml)

> Understand the work before making it. Use appropriate materials. Build with care.
> Measure the result. Keep a useful record. Maintain what is worth keeping.

This repository is proprietary — see `LICENSE`. See `CONTRIBUTING.md` before
making changes and `SECURITY.md` to report a vulnerability.

This repository holds the operating scaffold for Earthward's agent fleet: the
role-trained AI agents that support (never replace) the human disciplines of
the foundry, plus the shared data schema they all read and write.

## What's here

```
earthward-foundry/
├── docs/                       institutional framework, roles, build order
├── schema/                     shared traceability record schema (JSON Schema)
├── services/
│   ├── traceability/           RUNNABLE Phase-1 core-loop service (HTTP API)
│   ├── rescue/                 RUNNABLE rescue task force pipeline (HTTP API)
│   └── metrology/              RUNNABLE CMM programming + quality logic (library)
├── .github/workflows/ci.yml    lint + full test suite + Docker build, on every push/PR
├── docker-compose.yml          run traceability + rescue together locally
├── LICENSE / CONTRIBUTING.md / SECURITY.md
└── agents/                     one house per folder, one file per agent
    ├── leadership/
    ├── engineering/            Design what should exist
    ├── materials/              Understand what it is made from
    ├── forge/                  Transform material into physical form
    ├── assembly/                Turn components into systems
    ├── metrology/              Measure what was actually produced
    ├── validation/             Prove that it performs
    ├── records/                Preserve exactly what happened
    └── stewardship/            Maintain, improve, responsibly retire
```

## Three services are real and run today

These are not stubs — they're working implementations that enforce the
fleet's hard rules in code (human-only sign-off events, valid event
sequencing, no editing history) rather than trusting every agent's prompt
to self-police. Each has a passing test suite; the two HTTP services
require an API key (see **Running the services** below).

- **`services/traceability/`** — Phase 1 from the build order: an
  append-only part record store. See `services/traceability/README.md`.
- **`services/rescue/`** — the incident-response task force pipeline
  described in the project knowledge wiki. See `services/rescue/README.md`.
- **`services/metrology/`** — CMM programming and quality-engineering
  logic (`cmm.py`, `quality.py`); imported as a library, no HTTP API.

```bash
cd services/traceability && python3 demo.py   # narrated walkthrough, 2 intentional rejections
cd services/rescue && python3 live_demo.py    # narrated rescue pipeline walkthrough
```

## Running the services

Both HTTP APIs require an API key in production — see `.env.example` for
every variable and `SECURITY.md` for the full auth model.

```bash
# Locally, without Docker:
cd services/traceability && pip install -r requirements.txt \
  && TRACEABILITY_API_KEY=$(openssl rand -hex 32) python3 api.py
cd services/rescue && pip install -r requirements.txt \
  && RESCUE_API_KEY=$(openssl rand -hex 32) python3 api.py

# Or both together with Docker:
TRACEABILITY_API_KEY=... RESCUE_API_KEY=... docker compose up --build
```

## Testing and linting

```bash
# Per service (also runs standalone: python3 tests/test_x.py)
cd services/<name> && for f in tests/test_*.py; do python3 "$f"; done

# Lint (errors + pyflakes only, from repo root)
ruff check .
```

CI (`.github/workflows/ci.yml`) runs both of the above across a Python
3.11/3.12/3.13 matrix, plus a Docker build+boot smoke test, on every push
and PR to `main`.

## The eight houses

| House | Question it answers |
|---|---|
| Engineering | Design what should exist |
| Materials | Understand what it is made from |
| Forge | Transform material into physical form |
| Assembly | Turn components into systems |
| Metrology | Measure what was actually produced |
| Validation | Prove that it performs |
| Records | Preserve exactly what happened |
| Stewardship | Maintain, improve, and responsibly retire what was built |

## The non-negotiable rules (every agent, no exceptions)

1. **No agent self-certifies its own output.** Every irreversible or
   safety/quality/spend-relevant action requires a named human sign-off.
2. **No agent hides a failure to look complete.** Blocked, failed, or
   uncertain results are reported as such — never smoothed over.
3. **No agent invents a standard, spec, or certification.** If no real
   standard backs a recommendation, the agent says so and routes to a human.
4. **Every escalation names who it goes to** — never just "a human."

## Build order

This fleet is not meant to go live all at once. The proven order is:

1. **Traceability Agent** (`agents/records/traceability.md`) — every other
   agent's output is worthless without a real record trail.
2. **CMM Programming + Quality Engineering Agents** (`agents/metrology/`) —
   establishes the pass/fail backbone.
3. **Manufacturing Engineer + Mechanical Design Engineer Agents**
   (`agents/engineering/`) — gets one real part moving through the shop.
4. **Metallurgist + Foundry Process Engineer Agents** (`agents/materials/`)
   — once one part-family is proven.
5. Expand outward to Forge, Assembly, Validation, and the rest of
   Stewardship as volume justifies it.

See `docs/build-order.md` for the full rationale.

## Agent prompt format

Every agent file follows the same four-part structure so they drop directly
into a system prompt:

```
JOB:      what the agent does, precisely
NEVER:    the hard boundaries it does not cross
ESCALATE: the named-human handoff trigger(s)
OUTPUT:   the structured format it always responds in
```

## Shared spine

All house agents write events into one append-only part record, maintained
by the Traceability Agent. See `schema/part-record.schema.json`.

## Contributing

See `CONTRIBUTING.md` for the required structure for new agent files and
service modules, and the checks to run before opening a PR. CI enforces
the same checks on every push and PR to `main`.
