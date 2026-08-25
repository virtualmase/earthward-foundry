# Single-Customer Evidence-Ledger Pilot Playbook

## Pilot boundary

The first paid deployment is intentionally narrow: **one organization, one facility, one named part family, and one release-to-acceptance workflow**. The system must help authorized people collect and review evidence; it must not certify parts, replace the customer’s QMS/MES, or grant software authority to accept a part.

> The customer-facing proof is not “AI capability.” It is the ability to retrieve a complete, append-only, human-approved record for one controlled part family.

## MVP engineering backlog

The backlog below is ordered by release dependency. Every **P0** item is required before a customer records live pilot work. **P1** items may be scheduled after the first complete evidence loop, provided they do not weaken the P0 controls.

| ID | Priority | Deliverable and acceptance contract | Why it is required |
|---|---:|---|---|
| `PLT-01` | P0 | Create separate **staging** and **production** environments, versioned database migrations, configuration through a secret manager, and one-command rollback to the prior application release. A deployment cannot proceed with unreviewed migrations. | Quality records need controlled releases rather than ad hoc VM changes. |
| `IDN-01` | P0 | Implement authenticated user sessions with a verified identity-provider subject, organization invitation/activation, suspension, and an active-organization selector. Every mutation writes the authenticated `membership_id`; request-body provenance is never identity. | The current bearer-key model cannot attribute a customer action to a named user. |
| `TEN-01` | P0 | Implement the PostgreSQL organization schema and row-level security described in `docs/multitenant-workspace-design.md`. Automated tests must prove that an Organization A user cannot read, attach evidence to, export, or reference Organization B records. | Customer data must never rely only on application-side filters. |
| `LED-01` | P0 | Migrate the append-only part model to `part_revisions`, `part_units`, and `ledger_events`. Generate a transaction-safe per-part sequence number, prohibit runtime event updates/deletes, and permit corrections only as new events. | The existing integrity rule must survive the platform change. |
| `CTL-01` | P0 | Implement a server-side event-policy service. It validates required references, correction targets, inspection-before-acceptance, NCR preconditions, and current status derived from history. Rejections are explicit and logged. | Sequence and gap logic may not become optional in a web UI. |
| `CTL-02` | P0 | Require a named active human with the `quality_director` permission for `acceptance_decision`, `ncr_closed`, and `ncr_waived`. A service account cannot write these events. The final-acceptance action requires a deliberate confirmation and records the approving membership, timestamp, and evidence references. | Human control is a non-negotiable product promise. |
| `CTL-03` | P0 | Enforce separation of duties for final acceptance: the accepting membership cannot be the sole named human author of the qualifying inspection result or the only disposition author for an open NCR. When historical data lacks attributable human authorship, it is marked `legacy_import` and cannot satisfy this test by itself. | A single actor must not create the only evidence and accept it without independent review. |
| `EVD-01` | P0 | Add organization-scoped object storage for evidence. Each attachment has a generated opaque key, MIME/size allow-list, SHA-256, uploader membership, and immutable metadata. Files are scanned or quarantined before they can be opened in the workspace. | A reference alone is insufficient when the supporting report must be retrievable. |
| `IMP-01` | P0 | Build a two-step import flow: **validate/dry run** produces a machine-readable and human-readable error report; **apply** is allowed only after an authorized user reviews that report. Each batch has a manifest digest, source-file digest, importer identity, and audit event. | The customer must be able to correct bad source data before it enters the ledger. |
| `UI-01` | P0 | Deliver a simple browser workspace with: part search/list, immutable event timeline, evidence links, gap queue, record detail, controlled event entry, human acceptance modal, and export action. A non-developer quality user can complete these tasks without direct API calls. | The pilot cannot depend on engineering staff operating raw HTTP endpoints. |
| `EXP-01` | P0 | Produce a downloadable evidence package containing the record, ordered event history, evidence manifest, gap report, export metadata, and canonical SHA-256 digest. The interface and package label it as an integrity digest—not a signature, certification, or metrological attestation. | The customer needs an outside-the-system review artifact. |
| `AUD-01` | P0 | Record authentication, membership changes, import validation/apply, event rejection, approval, export, attachment access, and configuration changes in a separate append-only audit log. Only authorized support break-glass procedures may access cross-organization data, and every such access is logged and reviewable. | Product operations and customer evidence history have distinct audit needs. |
| `OPS-01` | P0 | Configure encrypted database/object backups, a named recovery owner, a documented retention policy, daily backup status monitoring, and one successful restore drill in staging before onboarding. | A single live VM disk is not a customer recovery plan. |
| `OPS-02` | P0 | Configure centralized structured logs, uptime/health checks, alert routing, error tracking, and a support contact. Store no raw evidence payload or bearer credentials in application logs. | The team needs a controlled way to detect and respond to pilot failures. |
| `TST-01` | P0 | Add regression tests for authorization, RLS isolation, append-only behavior, import rejection, policy gates, export digest reproducibility, attachment access, backup restoration, and the first customer’s configured flow. | Each customer-facing control needs a repeatable proof. |
| `IMP-02` | P1 | Add a documented API ingestion endpoint after CSV ingestion completes one real loop. Preserve the same dry-run, idempotency, validation, actor, and audit semantics. | API work should follow—not distract from—the first usable import path. |
| `UX-02` | P1 | Add saved filters, configurable dashboards, and controlled notification/reminder rules after the basic gap queue has proven useful. | These features are useful only after the core record is trusted. |

### Pilot release gate

The pilot is ready for live use only when a quality user can sign in, see only their organization’s records, import the sanitized baseline through a reviewed dry run, attach evidence, log an inspection result, see a deliberately blocked acceptance, record an authorized human decision, download an evidence package, and recover the same data in a staging restore test.

## Customer onboarding checklist

The customer should appoint one **Pilot Sponsor**—normally the Director of Quality—and one **Working Owner**, normally a Quality Engineer or Technical Records Specialist. The sponsor approves the workflow and success criteria; the working owner coordinates data preparation, role mapping, and weekly review.

| Stage | Customer action | Earthward action | Exit evidence |
|---|---|---|---|
| 1. Scope | Select one facility and one part family. Name the part number/revision range, work-order or serial/lot convention, and the first real release-to-acceptance flow. | Confirm the boundary is small enough to finish in the pilot and document exclusions. | Signed pilot scope sheet. |
| 2. Role map | Name the person/role that releases a revision, enters process evidence, runs inspection, opens an NCR, records disposition, approves acceptance, and audits records. | Map those people to workspace roles and identify conflicts with separation-of-duties. | Approved role map and access roster. |
| 3. Success baseline | Estimate the current elapsed time to find a complete record; count a recent record’s missing links; identify the customer’s definition of a useful exported package. | Define the pilot success measures and baseline worksheet. | One-page success plan. |
| 4. Security preflight | Confirm the permitted data classification, facility access constraints, retention period, approved file types, customer contacts, and escalation path. | Provide security/control summary and configure the organization workspace. | Written go/no-go for sanitized preflight data. |
| 5. Sanitize and package | Prepare the intake package in the exact format below. Replace customer, employee, supplier, program, drawing, and work-order identifiers with stable tokens if the preflight data must be sanitized. | Review the manifest, validate structure, and return an error/warning report without applying it. | Dry-run report accepted by the working owner. |
| 6. Configure | Confirm event types, required evidence references, facility label, approval policy, and export naming. | Create staging configuration, role invitations, and the import mapping. | Customer completes a staging walkthrough. |
| 7. Rehearse | Walk one representative record through inspection, a gap or NCR condition, a correction, and a blocked acceptance. | Verify controls, export the rehearsal package, and resolve defects. | Sponsor approves live-pilot readiness. |
| 8. Run and review | Operate one live loop with named human review; attend a weekly 30-minute review. | Monitor import/record issues, produce weekly evidence-completeness review, and collect product feedback. | Exported package reviewed by customer. |
| 9. Close out | Decide whether the output is useful, whether to expand to another part family, and what must change before managed production use. | Deliver outcome review, configuration record, and backlog decision. | Sponsor’s written acceptance, extension, or stop decision. |

### Sanitized-data rules

The preflight intake package must include **only data the customer is authorized to share**. Do not send controlled technical data, customer-identifying information, employee personal information, supplier pricing, unredacted customer purchase orders, credentials, or any data requiring export-control, contractual, or security approval. Use stable aliases such as `PART-FAM-01`, `UNIT-0007`, `WO-ALIAS-19`, `INSP-RPT-04`, and `USER-QA-01` so relationships and event order remain testable without disclosing the original values.

Keep the private alias crosswalk inside the customer’s approved environment. Earthward does not need the crosswalk to validate the pilot format. The access roster is the only intake artifact that includes user email addresses, and it must be transferred through the agreed secure channel—not embedded in event files.

## Exact intake package and data-ingestion format

Submit one UTF-8 ZIP file whose root contains the files below. CSV files use a comma delimiter, a single header row, RFC 4180 quoting, and no formulas. Timestamps are ISO 8601 with a UTC offset, for example `2026-08-24T14:30:00-07:00`. All identifiers are case-sensitive strings and must remain stable across files.

```text
evidence-ledger-intake/
├── intake_manifest.json
├── part_revisions.csv
├── part_units.csv
├── ledger_events.csv
├── evidence_manifest.csv
├── access_roster.csv                 # secure transfer only; not inside a general email ZIP
└── evidence/
    └── <only files listed in evidence_manifest.csv>
```

### Required files

| File | Required fields | Import behavior |
|---|---|---|
| `intake_manifest.json` | Organization alias, facility alias, pilot mode, submitter alias, all source-file SHA-256 digests, and declared event types | The digest must match every delivered file before parsing begins. |
| `part_revisions.csv` | `source_part_revision_key`, `part_number`, `revision`, `release_reference`, `release_date`, `facility_code` | One row becomes one controlled part revision. Duplicate source keys or part/revision pairs fail validation. |
| `part_units.csv` | `source_part_unit_key`, `source_part_revision_key`, `unit_identifier`, `work_order_reference`, `facility_code`, `created_at` | One row becomes the part unit that owns events. Every revision and facility reference must resolve in the same organization. |
| `ledger_events.csv` | `source_event_key`, `source_part_unit_key`, `sequence_hint`, `occurred_at`, `event_type`, `reference`, `source_provenance_type`, `source_provenance_label`, `corrects_source_event_key`, `payload_json`, `evidence_manifest_keys` | Each row becomes one candidate append-only event after policy validation. Source provenance remains descriptive; it does not authenticate or authorize the actor. |
| `evidence_manifest.csv` | `evidence_manifest_key`, `source_file_name`, `sha256`, `media_type`, `byte_size`, `storage_relative_path`, `external_reference`, `linked_source_event_keys` | Every linked local file must match its declared filename, byte size, media type, and SHA-256. An external reference may be supplied when a file is intentionally not transferred. |
| `access_roster.csv` | `email`, `display_name`, `workspace_role`, `facility_code`, `approval_authority` | Used only to invite and configure human users. It never creates historical event attribution from an imported source label. |

### Event import policy

For the first live pilot import, permit only `material_receipt`, `material_verification`, `process_step_start`, `process_step_complete`, `process_deviation`, `inspection_program_run`, `inspection_result`, `ncr_opened`, and `correction`. The importer rejects `acceptance_decision`, `ncr_closed`, `ncr_waived`, and `shipment` by default. Those authority-bearing actions must be performed in the workspace by an active, authorized human after the record is reviewed.

Historical files may be retained as evidence attachments and marked as `legacy_import`; they do not confer present-day user identity, approval authority, or an exception to the event policy. A `correction` row must reference an earlier event belonging to the same part unit. The importer does not infer missing references, timestamps, evidence, outcomes, or approvals.

### Import validation and apply rules

| Validation | Required result before apply |
|---|---|
| Package integrity | ZIP layout and every manifest/file SHA-256 digest match. |
| Schema | Required headers exist; files are UTF-8; JSON payloads parse to objects; timestamps are valid. |
| Referential integrity | Every part revision, part unit, correction, event, and evidence key resolves within the submitted organization. |
| Event integrity | `event_type` is allow-listed; reference is populated; `sequence_hint` is unique within a part unit; corrections point backward. |
| Policy integrity | Inspection result has a preceding inspection-program run; no disallowed authority-bearing action is imported; event order does not violate a hard precondition. |
| Evidence integrity | Every listed attachment matches its manifest entry; each event’s evidence keys resolve; unresolved external references are surfaced as warnings or errors according to the configured policy. |
| Idempotency | Re-submitting the same manifest digest does not create duplicate records. A changed package receives a new import batch ID. |
| Authorization | The person applying a validated import has `traceability_specialist`, `quality_engineer`, `quality_director`, or a defined import permission. |

The system returns `import_report.json` before any write. It includes `batch_id`, `manifest_sha256`, `valid_row_count`, `warning_count`, `error_count`, row-level error codes, and the deterministic proposed record count. The apply step must display that report and require an explicit confirmation by the authorized human. On apply, the system writes one `legacy_import` audit event per batch and preserves the source event key in a mapping table; it never overwrites an earlier applied batch.

## Definition of a useful pilot outcome

The customer and Earthward should jointly review three representative records: one routine inspection-and-acceptance path, one record with a missing or blocked item, and one record requiring a correction or NCR. Success means a Quality Director can quickly identify the responsible people, evidence references, gaps, and final human decision from the exported record, then state whether the package is useful for their internal review. It does not mean Earthward has certified the part or proven compliance with a standard.
