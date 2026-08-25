# Workspace Import PostgreSQL Migrations

The scripts in this directory target the future multi-tenant PostgreSQL workspace. They are **not** compatible with the current SQLite technical pilot and must not be run against that database.

| Order | File | Purpose |
|---:|---|---|
| 1 | `20260825_001_workspace_import_storage.sql` | Adds staged import batches, immutable source/report/finding records, idempotency reservations and responses, apply jobs, source-key mappings, and hash-chained audit events. |
| 2 | `20260825_002_workspace_import_rls.sql` | Creates non-login database group roles, enables and forces RLS, restricts grants, and exposes a controlled audit-append function. |

## Preconditions

Apply the foundational workspace schema first. It must contain `organizations`, `organization_memberships`, `facilities`, `service_principals`, `part_revisions`, `part_units`, `ledger_events`, `attachments`, and `evidence_links`, including the organization-scoped composite keys specified in `docs/multitenant-workspace-design.md`. The role running migrations needs authority to create extensions, types, roles, tables, triggers, functions, policies, and grants.

The HTTP app and import worker must not connect as the migration or schema-owner role. The backend sets `app.organization_id` and `app.membership_id` only from a validated session or trusted internal job, using `SET LOCAL` inside each transaction. Browser-originated values never become database context.

## Operational checks before a customer pilot

After migration, run a non-production proof that: the app role sees only its active organization; the worker cannot select a row after its organization context changes; direct event/audit modifications fail; a cross-tenant foreign-key reference fails; a duplicate idempotency key with a different request digest is rejected by the service; and a report state change cannot bypass the configured batch transition guard.
