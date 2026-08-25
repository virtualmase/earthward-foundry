# Pre-Acceptance Evidence-Baseline Import Contract

## Scope and status model

This contract adds a staged import capability to the future authenticated workspace API. It does **not** extend the current single-tenant bearer-key Flask API in place. The existing API accepts client-supplied `source` provenance; the workspace import API must instead derive organization, membership, and permission from an authenticated session and enforce tenant isolation with database row-level security.

The supported import purpose is intentionally narrow: establish a **pre-acceptance evidence baseline** for one organization’s bounded pilot workflow. The importer may create part revisions, part units, qualifying pre-acceptance events, attachment metadata, evidence links, source-key mappings, and an import audit event. It must never use a historical CSV row to create a present-day acceptance, NCR closure, NCR waiver, or shipment.

| Batch state | Meaning | Permitted next operation |
|---|---|---|
| `upload_pending` | Batch was created; no package is accepted yet. | Upload package or discard. |
| `uploaded` | Package digest and quarantine checks passed. | Start dry run. |
| `validating` | Validation is running. | Read status only. |
| `validated` | A report has zero errors and is eligible for one reviewed apply. | Read report, apply, or discard. |
| `rejected` | A report contains one or more errors. | Read report, discard, or create a new corrected batch. |
| `applying` | Transactional application is running. | Read status only. |
| `applied` | The complete baseline was committed once. | Read result and audit record. |
| `apply_failed` | No partial ledger commit may remain; failure details are in the safe API error/audit log. | Create a new batch after remediation. |
| `expired` | The reviewed report is stale or beyond its review window. | Create a new batch. |
| `discarded` | Customer or authorized staff abandoned the staged package. | Read audit metadata only. |

Each source package is immutable after upload. Any changed archive, changed manifest, changed role/policy configuration, or expired report requires a **new batch** and a new dry run. The default report lifetime is seven calendar days and should be configurable only to a shorter value for the pilot.

## Authentication and authorization

Every endpoint below requires a workspace session whose issuer, audience, expiration, and subject have been validated. The server sets the organization and membership context from that session at the start of the database transaction; it does not accept an `organization_id`, `membership_id`, `actor`, or `source` identity in a request body.

| Permission | Pilot roles | Endpoint use |
|---|---|---|
| `baseline_import.create` | Traceability Specialist, Quality Engineer, Quality Director | Create batch and upload package. |
| `baseline_import.validate` | Traceability Specialist, Quality Engineer, Quality Director | Start dry run and read report. |
| `baseline_import.apply` | Traceability Specialist, Quality Engineer, Quality Director | Explicitly apply an eligible baseline. |
| `baseline_import.read` | Above roles plus Auditor | Read batch status, report, and apply result. |

Organization Administrators do not receive import permission merely by being administrators. Service principals are excluded from the P0 workflow. If automation is added later, a scoped service principal may create or dry-run a batch but must never apply it; a named active human retains the apply action.

## Endpoint contract

The active organization is inferred from the authenticated workspace context, so organization IDs do not appear in URL paths. All endpoints are under `/v1`, return `application/json`, emit a correlation `X-Request-Id`, and require an `Idempotency-Key` UUID on create and apply requests.

| Method and path | Permission | Request | Success response | Notes |
|---|---|---|---|---|
| `POST /v1/import-batches` | `baseline_import.create` | JSON batch declaration | `201 Created` with batch ID and single-use upload path | Creates an immutable staging container. |
| `PUT /v1/import-batches/{batch_id}/package` | `baseline_import.create` | `application/zip` body; expected digest headers | `204 No Content` | Accepts one ZIP only while state is `upload_pending`. |
| `POST /v1/import-batches/{batch_id}/dry-run` | `baseline_import.validate` | Empty body | `202 Accepted` with state `validating` | Starts deterministic validation against the immutable package. |
| `GET /v1/import-batches/{batch_id}` | `baseline_import.read` | None | `200 OK` batch resource | Returns state and report/apply links, not raw evidence. |
| `GET /v1/import-batches/{batch_id}/report` | `baseline_import.read` | None | `200 OK` with `import_report.json` | Returns `409` while validation is still running. |
| `POST /v1/import-batches/{batch_id}/apply` | `baseline_import.apply` | JSON confirmation bound to report digest | `202 Accepted` with apply job ID | Applies a validated batch once, atomically. |
| `GET /v1/import-batches/{batch_id}/apply-jobs/{job_id}` | `baseline_import.read` | None | `200 OK` apply status | Returns resulting resource counts and audit event ID after commit. |
| `DELETE /v1/import-batches/{batch_id}` | `baseline_import.create` | None | `204 No Content` | Permitted only before apply; does not delete audit metadata. |

### 1. Create a batch

```http
POST /v1/import-batches
Content-Type: application/json
Idempotency-Key: 16d53a6e-4a87-485d-8969-a6c0f494d64f
Authorization: Bearer <workspace-session-token>

{
  "mode": "sanitized_preflight",
  "facility_code": "FAC-01",
  "source_package": {
    "filename": "evidence-ledger-intake.zip",
    "byte_size": 483920,
    "sha256": "c10edffb5a06b5db0c64d2f9bf78608b77d4c03e0350436c7e7f267dca0f374c"
  }
}
```

```json
{
  "import_batch_id": "4be6e796-bf09-45f8-9c97-b5f1ea4e6aa8",
  "state": "upload_pending",
  "upload": {
    "method": "PUT",
    "path": "/v1/import-batches/4be6e796-bf09-45f8-9c97-b5f1ea4e6aa8/package",
    "expires_at": "2026-08-31T21:00:00Z",
    "required_content_type": "application/zip",
    "required_sha256": "c10edffb5a06b5db0c64d2f9bf78608b77d4c03e0350436c7e7f267dca0f374c"
  }
}
```

The server validates the declaration before allocating storage: allowed mode, active facility in the organization, maximum size, ZIP filename, UUID idempotency key, and a lowercase hexadecimal SHA-256. The same idempotency key with the same request returns the original response; the same key with a different body returns `409` with `IMPORT-BATCH-002`.

### 2. Upload the immutable package

```http
PUT /v1/import-batches/4be6e796-bf09-45f8-9c97-b5f1ea4e6aa8/package
Content-Type: application/zip
Content-Length: 483920
X-Content-SHA256: c10edffb5a06b5db0c64d2f9bf78608b77d4c03e0350436c7e7f267dca0f374c
Authorization: Bearer <workspace-session-token>

<ZIP bytes>
```

The upload handler streams to organization-scoped quarantine storage, recomputes the digest, limits uncompressed ZIP size and entry count, rejects path traversal/symlinks/encrypted archives, and applies the agreed file-type and malware-scanning policy before state changes to `uploaded`. A package is never unpacked into a path derived from a customer filename. The server stores only a generated object key and digests in logs; it does not log raw evidence, CSV payloads, or session tokens.

### 3. Start a dry run

```http
POST /v1/import-batches/4be6e796-bf09-45f8-9c97-b5f1ea4e6aa8/dry-run
Authorization: Bearer <workspace-session-token>
If-Match: "c10edffb5a06b5db0c64d2f9bf78608b77d4c03e0350436c7e7f267dca0f374c"
```

```json
{
  "import_batch_id": "4be6e796-bf09-45f8-9c97-b5f1ea4e6aa8",
  "state": "validating",
  "report_path": "/v1/import-batches/4be6e796-bf09-45f8-9c97-b5f1ea4e6aa8/report"
}
```

The `If-Match` header prevents validation of a package other than the one the user reviewed. The dry-run worker verifies package integrity; parses required CSV/JSON; validates references, event order, and evidence links; evaluates the authority-history policy; and writes a new immutable report. It inserts no part, event, attachment, evidence link, or active approval record.

### 4. Read the report

`GET /v1/import-batches/{batch_id}/report` returns a document conforming to [`schema/import-report.schema.json`](../schema/import-report.schema.json). A validation rejection returns **`200 OK`** with `status: "rejected"` because the service successfully completed validation. The client renders each finding and keeps the Apply control unavailable when `apply.eligible` is `false`.

An authority-bearing row produces the following form. The actual SHA-256 values and UUIDs shown here are illustrative placeholders; production responses contain canonical lowercase hexadecimal values.

```json
{
  "report_type": "earthward.evidence-ledger.import-report",
  "schema_version": "1.0",
  "report_id": "9cf7a2f5-085a-4fcb-b8e0-6ed5d2a8f2a4",
  "import_batch_id": "4be6e796-bf09-45f8-9c97-b5f1ea4e6aa8",
  "organization_id": "1d77f5d8-ff6f-4e4c-aa31-a1902473450a",
  "status": "rejected",
  "mode": "sanitized_preflight",
  "validation_profile": "pre_acceptance_baseline_v1",
  "created_at": "2026-08-24T21:10:00Z",
  "completed_at": "2026-08-24T21:10:02Z",
  "source_package": {
    "filename": "evidence-ledger-intake.zip",
    "byte_size": 483920,
    "sha256": "c10edffb5a06b5db0c64d2f9bf78608b77d4c03e0350436c7e7f267dca0f374c",
    "manifest_sha256": "a3a95506845c27e226af8f21d68238e4bf96340bcd2df247db3660a19d650fd3",
    "storage_state": "clean"
  },
  "summary": {
    "source_file_count": 4,
    "rows_examined": 17,
    "rows_accepted": 16,
    "rows_rejected": 1,
    "finding_counts": {"errors": 1, "warnings": 0},
    "proposed_records": {"part_revisions": 1, "part_units": 1, "ledger_events": 16, "attachments": 2, "evidence_links": 2},
    "rejected_authority_events": [{"event_type": "acceptance_decision", "count": 1}]
  },
  "findings": [
    {
      "severity": "error",
      "code": "AUTH-HIST-001",
      "message": "Historical acceptance_decision cannot be imported into a pre-acceptance baseline.",
      "remediation": "Remove this row from the baseline. Retain the historic document as legacy evidence if needed, then have an active authorized Quality Director record any new decision in the workspace.",
      "location": {
        "file": "ledger_events.csv",
        "row": 19,
        "column": "event_type",
        "source_key": "EVT-019",
        "event_type": "acceptance_decision"
      },
      "rejected_action": "acceptance_decision",
      "related_source_keys": ["UNIT-0007"]
    }
  ],
  "apply": {
    "eligible": false,
    "requires_explicit_confirmation": true,
    "required_permission": "baseline_import.apply",
    "blocked_by_codes": ["AUTH-HIST-001"],
    "report_expires_at": "2026-08-31T21:10:02Z",
    "apply_precondition_sha256": "d71cdd4194f6924785c7e34c9d0e2ef0a5c7645f715a6e53f1ee684a8a5bb544"
  },
  "integrity_sha256": "d29539f1f5dcf97228c476e9d81f281842a7617664838796b38a9f09bc1676cc"
}
```

## Stable validation codes

`schema/import-report.schema.json` limits validation findings to the codes below. Messages are safe for the authorized user but must not expose SQL, file-system paths, credentials, or another organization’s identifiers.

| Code | Blocking rule | Required treatment |
|---|---|---|
| `PKG-001` | ZIP layout, declared file, digest, size, or safe-unpack rule failed. | Reject batch. |
| `PKG-002` | Package is quarantined, encrypted, contains unsafe archive entries, or fails malware policy. | Reject batch and retain only security audit metadata. |
| `SCHEMA-001` | Required file/header/field is missing or malformed. | Reject affected package. |
| `SCHEMA-002` | UTF-8, timestamp, CSV, or payload JSON cannot be parsed. | Reject affected package. |
| `REF-001` | Part revision, part unit, correction, or evidence reference cannot resolve inside the active organization. | Reject affected package. |
| `REF-002` | Correction target is not earlier or does not belong to the same part unit. | Reject affected package. |
| `EVENT-001` | Event type is unsupported for this profile or `reference` is missing. | Reject affected package. |
| `EVENT-002` | Duplicate/invalid sequence hint or source event key would make order ambiguous. | Reject affected package. |
| `POLICY-001` | Hard workflow precondition fails, such as an inspection result without a prior program run. | Reject affected package. |
| `EVIDENCE-001` | Attachment bytes or metadata do not match the evidence manifest. | Reject affected package. |
| `EVIDENCE-002` | Required event evidence link/external reference is absent. | Reject affected package. |
| `IDEMP-001` | Manifest or package was already applied, or a replay would duplicate evidence history. | Reject apply; create a new batch if source content changes. |
| `AUTH-001` | Caller lacks active membership or required import permission. | Return HTTP `403`; do not disclose batch existence cross-tenant. |
| `AUTH-HIST-001` | `acceptance_decision` appears in `ledger_events.csv`. | Reject row/batch; require controlled live human decision. |
| `AUTH-HIST-002` | `ncr_closed` appears in `ledger_events.csv`. | Reject row/batch; require controlled live human closure. |
| `AUTH-HIST-003` | `ncr_waived` appears in `ledger_events.csv`. | Reject row/batch; require controlled live human waiver. |
| `AUTH-HIST-004` | `shipment` appears in `ledger_events.csv`. | Reject row/batch; allow shipment only after controlled acceptance path. |
| `AUTH-HIST-005` | Import attempts to turn source provenance into a current workspace identity or approval authority. | Reject row/batch; historical labels remain descriptive provenance only. |
| `AUTH-HIST-006` | Import attempts to use legacy material alone to satisfy final-acceptance separation of duties. | Reject row/batch; require independent current review. |

`AUTH-HIST-001` through `AUTH-HIST-004` must be present as row-level `error` findings with the CSV file, row, source key, event type, and matching `rejected_action`. `AUTH-HIST-005` and `AUTH-HIST-006` are also errors and require the location/source key that triggered the attempt.

## HTTP error envelope

Transport, authentication, state, and authorization failures use [`schema/api-error.schema.json`](../schema/api-error.schema.json). They are distinct from a completed dry-run report.

```json
{
  "error": {
    "code": "IMPORT-APPLY-001",
    "message": "The import report is not eligible for apply.",
    "request_id": "0d1dd370-b4f6-495b-a0b4-7f2bc564a3d1",
    "retryable": false,
    "details": [
      {
        "field": "report_id",
        "reason": "Resolve every error in the import report and create a new batch."
      }
    ]
  }
}
```

| HTTP status | API code | When to use it |
|---:|---|---|
| `400` | `IMPORT-BATCH-001` or `IMPORT-PACKAGE-001` | Invalid endpoint request, malformed declaration, or digest/header mismatch before completed validation. |
| `401` | `AUTHENTICATION-001` | Missing, expired, or invalid workspace session. |
| `403` | `AUTHORIZATION-001` or `AUTH-001` | Active user lacks the permission; response must not reveal another tenant’s batch. |
| `404` | `IMPORT-BATCH-003` | Batch is absent or outside the caller’s organization. |
| `409` | `IMPORT-BATCH-002`, `IMPORT-BATCH-004`, `IMPORT-REPORT-001`, or `IMPORT-APPLY-002` | Idempotency conflict, invalid state transition, report still running, stale precondition, or already-applied batch. |
| `410` | `IMPORT-BATCH-005` | Reviewed report or batch has expired. |
| `413` | `IMPORT-PACKAGE-002` | Package exceeds configured size/entry limits. |
| `415` | `IMPORT-PACKAGE-001` | Request is not `application/zip`. |
| `429` | `RATE-LIMIT-001` | Rate limit reached. |
| `500` | `INTERNAL-001` | Unexpected server failure; log diagnostic detail only on the server. |

## Apply an eligible report

```http
POST /v1/import-batches/4be6e796-bf09-45f8-9c97-b5f1ea4e6aa8/apply
Content-Type: application/json
Idempotency-Key: b44a1208-471e-4279-b4d6-0f53f86ae71c
Authorization: Bearer <workspace-session-token>
If-Match: "d71cdd4194f6924785c7e34c9d0e2ef0a5c7645f715a6e53f1ee684a8a5bb544"

{
  "report_id": "9cf7a2f5-085a-4fcb-b8e0-6ed5d2a8f2a4",
  "confirmation": "APPLY PRE-ACCEPTANCE BASELINE"
}
```

The server must re-check the batch state, report ID, report digest, expiry, active organization, active membership, `baseline_import.apply` permission, source package digest, validation profile, and policy/role-configuration version immediately before applying. It then performs a single tenant-scoped database transaction in dependency order: part revisions, part units, clean attachment metadata, evidence links, allowed pre-acceptance events, source-key mappings, and an append-only `legacy_import` audit event.

If any insert or policy validation fails, the transaction rolls back completely. There is no partial baseline and no “best-effort” event insertion. Successful application returns a job resource such as:

```json
{
  "apply_job_id": "903cf9b1-4172-43d8-bcd5-c4caccebb2cb",
  "import_batch_id": "4be6e796-bf09-45f8-9c97-b5f1ea4e6aa8",
  "state": "applying",
  "status_path": "/v1/import-batches/4be6e796-bf09-45f8-9c97-b5f1ea4e6aa8/apply-jobs/903cf9b1-4172-43d8-bcd5-c4caccebb2cb"
}
```

## Data model and operational requirements

Implement staging data separately from the live ledger: `import_batches`, `import_source_files`, `import_reports`, `import_findings`, `import_apply_jobs`, and `import_source_key_mappings`. Each table carries `organization_id` and has row-level security enabled. The final mapping table records source keys without changing the original event history. The full source package and historic approval documents may remain available as immutable `legacy_import` evidence, but none of their historical labels can create a current user session, membership, quality authority, or final state.

The worker must process CSV/JSON parsing and file scanning outside the request thread, but it must set a tenant-scoped database context for every metadata operation. Store report data and evidence references; do not expose raw unapproved content in application logs or user-visible stack traces. Audit every create, upload, dry run, report retrieval, apply attempt, apply result, expiration, discard, and authorized support break-glass action.
