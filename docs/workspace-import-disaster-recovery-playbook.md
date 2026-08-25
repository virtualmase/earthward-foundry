# Workspace Import Disaster Recovery and Backup Verification Playbook

## Purpose, scope, and production boundary

This playbook verifies that the tenant-scoped baseline-import storage can be recovered **with its tenant isolation, immutable reports, idempotency records, source mappings, and audit trail intact**. It covers the PostgreSQL tables introduced in `migrations/20260825_001_workspace_import_storage.sql` and their RLS policies in `migrations/20260825_002_workspace_import_rls.sql`.

> **This is a recovery-verification design, not a statement that a production backup system exists today.** The current SQLite technical pilot remains separate. Do not run these restore procedures on a production database, active customer tenant, or live object-storage prefix.

PostgreSQL supports logical dump, physical/file-system backup, and continuous archiving approaches. `pg_verifybackup` checks physical-backup manifests, file integrity, and required WAL readability, but PostgreSQL explicitly says that it does not replace a test restore and data validation. [1] [2] This playbook therefore treats **automated isolated restore plus domain checks** as the proof of recoverability.

## Recovery objectives that require owner approval

The pilot sponsor, Quality Director, and service owner must set measurable service objectives before the first customer import. The table below provides proposed starting targets only; it does not create a guarantee.

| Objective | Proposed pilot target | Approval authority | Evidence |
|---|---:|---|---|
| **Recovery Point Objective (RPO)** | No more than 15 minutes of committed database data loss. | Service owner and customer sponsor | Base-backup/WAL archive timestamps and successful point-in-time drill. |
| **Recovery Time Objective (RTO)** | Restore verified workspace data within 4 hours of declared disaster. | Service owner and customer sponsor | Timed quarterly restore drill. |
| **Backup integrity** | Every successful physical backup passes manifest/WAL verification. | Platform owner | `pg_verifybackup` record and immutable artifact digest. |
| **Tenant recovery correctness** | Restored tenant A is inaccessible in tenant B context, and vice versa. | Security owner | Automated RLS negative-test record. |
| **Audit continuity** | No gap, duplicate sequence, or hash-link mismatch in restored audit chains. | Quality and security owners | Restore-verification report. |

## Backup architecture options

The first two options are viable for the core database. The logical export is a supplementary portability and evidence check; it is not sufficient by itself for low-RPO point-in-time recovery.

| Approach | What runs automatically | Strengths | Tradeoffs and minimum safeguards |
|---|---|---|---|
| **Managed PostgreSQL backup and point-in-time recovery** | Provider-managed base backups and WAL/PITR, plus a scheduled isolated restore verifier. | Lowest operational burden; suitable default when the provider supports encrypted cross-location backups and PITR. | Confirm recovery window, regional failure model, encryption-key access, restore API, backup retention, and audit logging with the provider. Run an independent restore drill; “backup enabled” is not proof of recovery. |
| **Self-managed physical base backup plus continuous WAL archive** | Scheduled `pg_basebackup`, continuous WAL archiving, `pg_verifybackup`, immutable artifact upload, and scheduled restore drill. | Clear control of RPO/RTO and artifact custody. | Requires a hardened run host, protected archive credentials, alerting for WAL lag/failure, and tested recovery automation. Continuous recovery requires a continuous WAL sequence back to the base-backup start. [3] |
| **Encrypted logical custom dump as a secondary control** | Scheduled `pg_dump -Fc`, restore to a disposable database, and domain validation. | Portable, selective inspection via `pg_restore`, and useful for migration or a table-level investigation. | Not the primary PITR mechanism. Restore only into an isolated environment; partial dump/restore may omit dependencies, and dump content must be treated as trusted administrative code. [4] |

For recurring deterministic checks, run the verification pipeline in a managed scheduled job with isolated database credentials and artifact storage—not in a conversational session. The lighter option is a scheduled restore check with provider-native backups; the more controlled option is a dedicated recovery run host for physical base backups, WAL validation, and restore operations. Select the route based on the actual PostgreSQL hosting model, required RPO/RTO, and whether the backup provider supplies a restore API.

## Data set and artifact inventory

| Class | Tables or storage | Backup requirement | Restore verification |
|---|---|---|---|
| Core staged-import state | `import_batches`, `import_source_files`, `import_reports`, `import_findings`, `import_apply_jobs` | Included in physical backup/PITR; represented in supplemental logical export. | Row counts, status/relation constraints, report-to-batch one-to-one relationship, expiry fields. |
| Replay safety | `import_idempotency_keys`, `import_idempotency_responses` | Same recovery set as batches and jobs. | Uniqueness and request/response-digest relationships remain intact. |
| Applied-source traceability | `import_source_key_mappings` | Same recovery set as applied jobs and live ledger tables. | Every mapping references a restored batch/job and no source key maps across organizations. |
| Accountability | `audit_events` and immutable external logs | Independent retention from package/object data; replicated immutable copy. | Per-organization sequence starts/continues correctly; hash link verifies; no update/delete grant. |
| Package/evidence objects | Quarantine, clean evidence, export, and backup prefixes in object storage | Versioned, encrypted, organization-prefixed, retention-policy protected; object manifest captured with database backup. | Object count/digest/sample retrieval matches `import_source_files` and evidence metadata without exposing content publicly. |
| Schema and authorization | Migrations, roles, grants, RLS policies, service configuration, identity configuration | Versioned source plus database/global-object backup and encrypted configuration export. | Required migrations, roles, RLS `FORCE` flag, grants, and policy names exist after restore. |

> A database-only restore is insufficient when evidence files live in object storage. A recovery set is valid only if it binds database backup identity, WAL/PITR horizon, object-manifest digest, schema version, and verification result into one signed/immutable operations record.

## Automated verification pipeline

The pipeline uses a **fresh isolated recovery environment** for every run. It never restores into the production cluster, never uses a customer organization as a test fixture, and never writes a production `organization_id` into a test record.

| Step | Automated action | Fail closed when | Required retained evidence |
|---:|---|---|---|
| 1 | Create run ID and capture backup catalog entry, schema/migration version, source cluster version, target recovery environment ID, and planned recovery timestamp. | Catalog lacks a complete base backup + required WAL range, or a recovery environment is not isolated. | `recovery-run.json` initial record. |
| 2 | Verify physical backup manifest/checksums/WAL with `pg_verifybackup`; separately verify encrypted object-manifest digest and artifact existence. | Any checksum, manifest, required-WAL, encryption, or object-manifest verification fails. | Command exit code, tool version, manifest digest, artifact URI without credentials. |
| 3 | Restore to a new disposable database or provider recovery instance; recover to the selected target timestamp for a PITR drill. | Restore command fails, migrations/roles are absent, or recovery target cannot start. | Restore log with secrets redacted, elapsed time, recovery target. |
| 4 | Apply post-restore hardening: disable public ingress, set recovery test identity, block outbound integrations, and mark environment `RESTORE_TEST_ONLY`. | Recovery environment has production egress, customer notifications, or production write credentials. | Network/configuration attestation. |
| 5 | Run schema, role, RLS, constraint, idempotency, audit-chain, and tenant-isolation checks. | Any expected table/policy/grant/constraint is absent; any cross-tenant read/write succeeds. | Machine-readable `restore-verification.json`. |
| 6 | Verify object manifest with authorization-controlled sample reads and digest checks; do not bulk-download sensitive evidence unless the approved drill requires it. | Object missing, digest mismatch, unexpected public access, or orphaned DB/object relation. | Sample plan, digest outcomes, access-control result. |
| 7 | Record RPO and RTO actuals; compare with approved objectives. | Target exceeded, verification incomplete, or fail-open cleanup occurs. | Final run record, alerts, and issue/ticket link. |
| 8 | Destroy recovery database/instance and ephemeral object copies; retain only approved encrypted artifacts and audit results. | Cleanup cannot prove deletion/isolation, or artifact retention policy is unclear. | Cleanup attestation and deletion job ID. |

The pipeline must emit a nonzero outcome on **any** failed verification and page the on-call owner. A “backup succeeded” event does not close an incident if restore verification has failed or has not run within the approved interval.

## Required automated checks

### 1. Physical backup and WAL checks

Run the version-matched `pg_verifybackup` against each base backup before accepting it for the recovery catalog. PostgreSQL verifies the backup manifest, files, checksums, and required WAL parsing, while still requiring test restores as a separate proof. [2]

```bash
pg_verifybackup --exit-on-error "$RESTORE_STAGE/base-backup"
```

For continuous recovery, verify that the archived WAL sequence reaches from the selected base-backup start through the declared recovery target. PostgreSQL notes that recovery depends on that continuous range and that archive failures/lag require monitoring. [3]

### 2. Schema, RLS, and grant checks

Run these checks against the recovery environment using a controlled administrative verification session. They are intentionally table- and policy-specific rather than relying on a generic “database is up” probe.

```sql
-- Required tenant-owned tables are protected and forced through RLS.
SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
FROM pg_class AS c
WHERE c.relname IN (
  'import_batches', 'import_source_files', 'import_reports', 'import_findings',
  'import_idempotency_keys', 'import_idempotency_responses', 'import_apply_jobs',
  'import_source_key_mappings', 'audit_events'
)
ORDER BY c.relname;

-- Runtime roles must never own protected tables or hold BYPASSRLS.
SELECT r.rolname, r.rolbypassrls, EXISTS (
  SELECT 1
  FROM pg_class c
  WHERE c.relowner = r.oid
    AND c.relname IN ('import_batches', 'import_reports', 'audit_events')
) AS owns_protected_table
FROM pg_roles AS r
WHERE r.rolname IN (
  'earthward_workspace_app', 'earthward_import_worker', 'earthward_workspace_readonly'
)
ORDER BY r.rolname;
```

The run fails if any required table lacks both RLS flags, if a runtime role has `rolbypassrls = true`, or if a runtime role owns a protected table. PostgreSQL documents that owners and `BYPASSRLS` roles can bypass ordinary RLS enforcement. [5]

### 3. Tenant isolation and relationship checks

Seed or restore two **synthetic recovery tenants** before the drill. For each tenant, use an active synthetic membership and the `earthward_workspace_readonly` role. Set `app.organization_id` and `app.membership_id` transaction-locally, then perform all of the following:

| Test | Expected result |
|---|---|
| Tenant A reads its own batch/report/finding/job/audit rows. | Visible records are returned. |
| Tenant A reads a known tenant B batch ID and report ID. | No rows returned; public API layer normalizes this to `404`. |
| Tenant A attempts a cross-tenant source mapping or foreign-key reference. | Constraint/RLS rejection; no row committed. |
| Tenant A reads `import_idempotency_keys` or responses owned by tenant B. | No rows returned. |
| Read-only role attempts update/delete against reports, findings, mappings, or audit events. | Permission/append-only rejection. |
| Worker context with tenant A attempts to insert tenant B row. | `WITH CHECK` RLS rejection. |

Run the same cases through the HTTP API with synthetic credentials. Database-only checks are necessary but do not prove endpoint object authorization or safe error normalization.

### 4. Import-report and replay-safety checks

The restored database must prove that `import_reports` has exactly one report per batch and every report corresponds to the same organization, package digest, policy fingerprint, and expiry fields expected by its batch. Verify `import_findings` ordinals are unique per report, `AUTH-HIST` findings retain their required source metadata, and a report with errors cannot be marked eligible by a stale or altered apply request.

For idempotency, verify that every `import_idempotency_responses` row references one key in the same organization, that response/request digests are well-formed, and that a restored matching retry returns the recorded result instead of creating a second batch or apply job. Then run `tools/workspace_import_loadtest/stress_import_concurrency.py` against the recovered API using **only synthetic disposable data**.

### 5. Audit-chain and append-only checks

For each organization in the verification set, recompute the audit chain in `audit_sequence` order from the same canonical event representation used by `workspace_assign_audit_chain()`. Verify that: sequence values are gap-free and unique; each `previous_event_sha256` matches the prior `event_sha256`; the recomputed digest equals stored `event_sha256`; and only the approved audit function can insert new audit rows under runtime roles. Any mismatch is a security incident until explained.

The verifier must also attempt direct `UPDATE` and `DELETE` against `audit_events`, `import_reports`, `import_findings`, and `import_source_key_mappings` using the relevant runtime roles. Each attempt must fail because of the grants and append-only triggers.

### 6. Object-storage consistency checks

Query the recovered `import_source_files` and package metadata to produce an expected object-manifest digest. Compare it to the backup catalog’s stored manifest. Perform signed, authorization-controlled sample reads across each object class—quarantine, clean evidence, and export—not public URL access. Confirm that the object key’s organization prefix matches the metadata organization, the object digest matches the stored digest, and an unauthorized tenant cannot retrieve it.

## Restore drills and incident paths

| Drill | Frequency | Recovery target | Pass condition |
|---|---|---|---|
| Backup artifact verification | Every base backup | Backup artifact only | `pg_verifybackup`, object-manifest, and encryption checks pass. |
| Logical restore smoke test | Daily | Fresh disposable database | Schema, import tables, RLS roles/policies, and synthetic tenant checks pass. |
| Full physical restore | Weekly | Isolated recovery cluster | Database starts; full domain validation and object-manifest sampling pass. |
| Point-in-time recovery | Quarterly and after any archiving change | Isolated recovery cluster to a documented timestamp | Recovery reaches target timestamp inside RTO and preserves tenant/audit invariants. |
| Incident tabletop | Quarterly | No data restore | On-call, Quality Director, and service owner can execute escalation and communication sequence. |
| Post-migration drill | Before/after every schema or RLS migration | Isolated recovery cluster | Migrated schema restores, policies apply, and prior backup set remains recoverable. |

## Failure handling and escalation

| Failure class | Immediate action | Escalation | Customer communication |
|---|---|---|---|
| Backup verification failure | Mark backup unusable; retain for forensics; start a new backup; verify the latest known-good set. | Platform owner immediately; security owner if integrity issue. | Notify sponsor if no valid recovery point remains within approved RPO. |
| WAL gap/archive lag | Stop claiming PITR coverage; preserve current WAL; remediate archive path/capacity. | Platform owner immediately. | Notify sponsor when approved RPO is exceeded or unknown. |
| Restore or RTO failure | Preserve failed recovery environment; do not retry destructively over evidence. | Incident lead, platform, Quality Director. | Provide factual status, recovery point, and next update time—never assert compliance/certification. |
| Cross-tenant/RLS failure | Disable affected workspace endpoint or recovery environment; rotate runtime credentials; investigate role/context leak. | Security owner and incident lead immediately. | Treat as potential security incident under the disclosure process. |
| Audit-chain mismatch | Freeze destructive retention actions; retain artifacts; verify alternate backup set. | Security and Quality Directors. | Escalate according to customer contract and impact assessment. |

## Required recovery-run record

Every automated run writes an immutable, redacted operations record such as:

```json
{
  "run_type": "weekly_physical_restore",
  "run_id": "<uuid>",
  "started_at": "<ISO-8601>",
  "backup_set_id": "<provider-or-catalog-id>",
  "recovery_target": "<ISO-8601-or-latest>",
  "schema_migration_head": "20260825_002_workspace_import_rls",
  "artifact_manifest_sha256": "<sha256>",
  "pg_verifybackup": "passed",
  "restore": "passed",
  "tenant_isolation": "passed",
  "audit_chain": "passed",
  "object_manifest": "passed",
  "actual_rpo_seconds": 0,
  "actual_rto_seconds": 0,
  "cleanup": "passed",
  "operator": "automated-recovery-verifier"
}
```

Never include database URLs, credentials, raw evidence, customer source files, signed object URLs, or unredacted error stacks in this record.

## Implementation checklist

Before enabling a customer workspace, the service owner must: approve RPO/RTO; select one backup architecture; provision encrypted immutable backup storage and an isolated restore environment; give the recovery verifier its own least-privilege credentials; implement the database/object manifest linkage; schedule the verification cadence; route failures to on-call; retain run records; and perform one supervised recovery drill. The Quality Director must review the post-restore invariant report for the pilot workflow.

## References

[1] [PostgreSQL, *Backup and Restore*](https://www.postgresql.org/docs/current/backup.html)

[2] [PostgreSQL, *pg_verifybackup*](https://www.postgresql.org/docs/current/app-pgverifybackup.html)

[3] [PostgreSQL, *Continuous Archiving and Point-in-Time Recovery*](https://www.postgresql.org/docs/current/continuous-archiving.html)

[4] [PostgreSQL, *pg_dump*](https://www.postgresql.org/docs/current/app-pgdump.html)

[5] [PostgreSQL, *Row Security Policies*](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
