# Staged Baseline-Import Security Threat Model

## Scope and security objective

This threat model covers the Evidence-Ledger workflow that stages a customer ZIP package, validates it without writing live records, returns an immutable report, and applies an eligible pre-acceptance baseline through a separate explicit human action. It applies to the future multi-tenant workspace API, worker, PostgreSQL database, object storage, and operational audit path. It does **not** represent the current single-tenant SQLite technical pilot as production-ready.

> **Primary security objective:** no caller, worker, stored package, historical provenance label, or retry may create a cross-tenant data effect, a hidden partial import, or a present-day authority-bearing quality action without an authenticated and authorized human decision.

The model uses PostgreSQL RLS as a database enforcement layer in addition to endpoint authorization. PostgreSQL warns that normal RLS behavior can be bypassed by superusers, `BYPASSRLS` roles, and ordinarily by table owners; it also warns that constraints and foreign keys can create covert channels. [1] [2] The migration therefore assigns tables to a non-runtime schema owner, forces RLS, avoids `BYPASSRLS` in runtime roles, and treats tenant-context tests as release gates.

## Assets, trust boundaries, and assumptions

| Asset | Security property that must hold | Primary control owner |
|---|---|---|
| Workspace identity and membership | An action is attributable to an active human membership, not a request-body `source` object. | Identity and API service |
| Organization boundary | A tenant can read or mutate only its own staged and live records. | PostgreSQL RLS, composite keys, API authorization |
| Staged package and attachments | Untrusted bytes cannot execute, escape storage, or become visible before quarantine and policy checks. | Upload gateway and validation worker |
| Import report | A displayed report corresponds to one immutable package and one known validation/policy state. | Worker, report digest, `If-Match` precondition |
| Live evidence ledger | Apply is atomic, append-only, ordered, and limited to allowed pre-acceptance records. | Apply service and database transaction |
| Quality authority | Historical labels and service accounts cannot create acceptance, waiver, NCR closure, or shipment. | Event policy and role checks |
| Idempotency reservation | A retry returns the original result; a changed request cannot reuse the same key. | API service and database uniqueness |
| Audit trail | Material security and import events are attributable, append-only, and reviewable. | Database trigger, audit service, operations |
| Keys, tokens, and secrets | Secrets are never logged, embedded in source, or accepted from URLs. | Identity platform, secret manager, logging |

The design assumes TLS terminates only at a controlled ingress; the identity provider validates session issue, audience, signature, expiry, and revocation state; the worker accepts only trusted internal jobs; and a customer’s security review determines which sanitized data is allowed in a pilot. APIs must authorize each object-level action and enforce workflow state server-side rather than relying on UI sequence. [4] [5]

## Lifecycle-specific security invariants

The following assertions are release-blocking and must be proven in integration testing before customer use.

| ID | Invariant |
|---|---|
| `INV-01` | `organization_id` is derived from verified runtime context; it is never accepted from a browser or ZIP field as authorization input. |
| `INV-02` | A user without an active membership receives no cross-tenant batch, report, attachment, or audit visibility. |
| `INV-03` | A dry run creates no `part_revisions`, `part_units`, `ledger_events`, `attachments`, `evidence_links`, or final-quality action. |
| `INV-04` | The package digest, report digest, policy fingerprint, role-policy version, report expiry, and active membership are rechecked immediately before apply. |
| `INV-05` | An apply transaction commits all allowed records and audit evidence together or commits none. |
| `INV-06` | `acceptance_decision`, `ncr_closed`, `ncr_waived`, and `shipment` are never imported from historical rows. |
| `INV-07` | The same idempotency key and canonical request return the prior response; the same key and a changed canonical request fail closed. |
| `INV-08` | `import_reports`, findings, source mappings, idempotency records, and audit events cannot be updated or deleted by runtime application roles. |
| `INV-09` | No runtime database role owns protected tables or possesses `BYPASSRLS`. |
| `INV-10` | Diagnostics, API errors, and logs do not expose another organization’s identifier, raw evidence content, credentials, SQL, object-storage paths, or stack traces. |

## Threat and mitigation matrix

Likelihood and impact are qualitative for prioritization during the first pilot. A residual rating of **High** blocks launch; **Medium** requires a named owner, test, and documented operating control; **Low** remains monitored through the pilot.

| ID | Threat / attack path | Affected phase | Impact | Required mitigation | Verification evidence | Residual owner / rating |
|---|---|---|---|---|---|---|
| `TM-01` | A user changes `batch_id` or `job_id` to enumerate another organization’s records. | Read, apply, discard | Cross-tenant disclosure or mutation | Derive organization from session; RLS on every owned table; normalize out-of-tenant lookup to `404`; no tenant ID in browser path. | Cross-tenant GET/PUT/POST/DELETE test matrix. | Backend lead / Medium |
| `TM-02` | A runtime connection uses a table-owner role, superuser, inherited role, or `BYPASSRLS` privilege. | All database access | Full tenant-isolation failure | Separate no-login schema owner from app/worker roles; `FORCE ROW LEVEL SECURITY`; check role attributes in deployment CI. [1] | CI query against `pg_roles`, negative RLS tests. | Platform owner / Medium |
| `TM-03` | A pooled connection retains `app.organization_id` or `app.membership_id` from the prior request. | API and worker transactions | Cross-tenant read/write | Set context using `SET LOCAL` only inside an explicit transaction; reset/rollback on checkout; prohibit session-level `SET`; test alternating-tenant requests on one connection. | Connection-pool isolation integration test. | Backend lead / Medium |
| `TM-04` | A forged, stolen, expired, wrong-audience, or revoked token is accepted. | Every endpoint | Identity takeover | Verify signature with pinned issuer/JWK strategy plus `iss`, `aud`, `exp`, `nbf`, and revocation/session state; short-lived tokens; no token in URL. [4] | Authentication negative tests and token-revocation drill. | Identity owner / Medium |
| `TM-05` | Membership is suspended or role changed after report creation, but the caller still applies it. | Apply | Unauthorized live write | Re-evaluate active membership, permission, and role-policy version immediately before apply; expire report if policy state changed. | Suspend user/change role between report and apply test. | Quality + backend / Low |
| `TM-06` | A client calls apply, upload, or validation endpoints out of sequence. | State machine | Bypass of review/quarantine | Server-side finite state transition guard; route allow-list; `If-Match` package/report preconditions; UI is not a control. [4] | State-transition fuzz tests. | Backend lead / Low |
| `TM-07` | Two concurrent apply requests race and duplicate ledger records. | Apply | Duplicate/contradictory evidence | Unique `import_batch_id` in apply jobs; idempotency reservation; row/advisory lock; one transaction; replay original response for matching retry. | Concurrent apply test with two workers. | Backend lead / Low |
| `TM-08` | Same idempotency key is reused with a changed request or another actor. | Create/apply | Confused-deputy or changed intent | Bind key to organization, membership, operation, and canonical request SHA-256; reject changed digest with `409`; minimum retention exceeds client retry window. | Same-key/same-body and same-key/different-body tests. | Backend lead / Low |
| `TM-09` | A report is applied after package replacement, policy change, report expiry, or role-map change. | Apply | Stale validation accepted | Immutable package storage; report/policy/role fingerprints; report expiration; recompute and compare all preconditions inside apply transaction. | Package/report/policy mutation simulation. | Backend + quality / Low |
| `TM-10` | A ZIP bomb, malformed archive, symlink, traversal path, encrypted archive, or excessive entries exhausts storage/CPU or writes outside quarantine. | Upload/validate | Denial of service or code/data exposure | Stream upload to quarantine; cap compressed and uncompressed bytes, nesting, entries, path depth, and processing time; reject absolute/traversal/symlink entries; never extract to customer-derived path. [3] | Archive corpus test and worker resource-limit test. | Platform owner / Medium |
| `TM-11` | A malicious PDF, spreadsheet, image, or embedded active content infects a reviewer or parser. | Upload/review | Malware, XSS, client compromise | Allow-list business-critical media types; sniff signature in addition to declared type; antivirus/sandbox; isolate parser; serve downloads via authorization handler with `Content-Disposition: attachment`, `nosniff`, and no inline active content by default. [3] | Malware/safe-file test corpus and browser download test. | Security owner / Medium |
| `TM-12` | CSV formula injection executes when an export/report is opened in a spreadsheet. | Dry run/report/export | Client-side data exfiltration | Treat CSV cells beginning with `=`, `+`, `-`, or `@` as data; escape on any CSV export; render reports as JSON/HTML text, never spreadsheet formulas. | Formula payload regression tests. | UI/export owner / Low |
| `TM-13` | Evidence link causes backend fetch of a malicious or internal URL (SSRF). | Validation/apply | Internal network access/data theft | Do not fetch customer-provided external references during import; store them as opaque text; any future fetcher uses strict scheme, DNS/IP, redirect, and egress allow-lists. [5] | URL/redirect/private-IP rejection suite. | Backend lead / Low |
| `TM-14` | Object key, signed URL, or raw attachment is disclosed through logs, error details, cache, referrer, or broad object-store policy. | Upload/read/export | Evidence disclosure | Opaque organization-prefixed object keys; short-lived audience-bound download authorization; no public buckets; `Cache-Control: no-store`; redact logs and referrers; test cross-tenant object retrieval. [3] [4] | Storage-policy audit and download authorization tests. | Platform owner / Medium |
| `TM-15` | Client trusts `Content-Type`, filename extension, manifest hash, or a single digest as the only safety/integrity signal. | Upload/validate | Malicious or substituted content | Validate type, signature, size, archive structure, and computed digests independently; use digest as tamper evidence—not as an approval, signature, or certification. [3] | Mismatched header/extension/signature tests. | Worker owner / Low |
| `TM-16` | Parser ambiguity, duplicate CSV headers, JSON duplicate keys, Unicode confusables, or inconsistent canonicalization changes validation meaning. | Validate | Validation bypass or incorrect report | Strict UTF-8, unique headers/source keys, schema parser that rejects duplicate JSON keys, normalized identifier policy, canonical serialization version, and fixed time-zone rules. | Differential parser/canonicalization tests. | Worker owner / Medium |
| `TM-17` | Importer uses historical `source` provenance to create a current membership, authority, or independent review. | Validate/apply | Improper quality approval | Explicit `AUTH-HIST-005`/`006` detection before generic schema rejection; provenance is descriptive only; live acceptance requires current authorized human and separation-of-duties check. | Six AUTH-HIST integration tests plus live acceptance negative tests. | Quality + backend / Low |
| `TM-18` | A historical acceptance, NCR close/waiver, or shipment row becomes a live state. | Validate/apply | Unauthorized release/disposition | Reject `AUTH-HIST-001`–`004`; retain historic document only as `legacy_import` evidence; no present state change. | Four event-specific integration tests. | Quality + backend / Low |
| `TM-19` | Worker or client manipulates event order, correction target, evidence links, or report counts to hide a gap. | Validate/apply | Loss of traceability integrity | Validate sequence/reference/correction constraints; server derives status; source-key mappings append only; recompute report digest and counts; no best-effort partial apply. | Gap, correction, and rollback tests. | Backend lead / Medium |
| `TM-20` | A worker job is forged, replayed, or runs with a wrong organization context. | Worker/apply | Cross-tenant or unauthorized writes | Signed/queued internal job with job ID and expected org; worker re-loads batch under RLS; no direct browser queue publish; idempotent job execution; per-job audit events. | Forged job and replay tests. | Platform owner / Medium |
| `TM-21` | Resource exhaustion through huge uploads, rapid dry runs, polling, apply retries, or expensive parser work. | All API phases | Availability/cost loss | Ingress request limits, organization/user quotas, async worker concurrency limits, bounded parse CPU/time, rate limits, 429 handling, back-pressure, alerting. [4] [5] | Load and quota tests; cost/latency alert drill. | Platform owner / Medium |
| `TM-22` | API errors reveal object existence, file paths, SQL, stack traces, validation payloads, or another tenant’s data. | All endpoints | Information disclosure | Stable error envelope; out-of-tenant `404`; authorized report holds detailed findings; generic external errors; no raw exception serialization. [4] | Error-response snapshot tests. | Backend lead / Low |
| `TM-23` | Audit events can be changed, deleted, fabricated, or reordered. | All phases | Accountability failure | Append-only triggers; no runtime `UPDATE`/`DELETE`; per-tenant sequence/hash chain; least-privilege audit append function; external immutable backup and periodic chain verification. | Tamper attempt tests and daily chain-verification job. | Security owner / Medium |
| `TM-24` | Audit metadata becomes a sensitive-data dump or log-injection vector. | Audit | Privacy breach/forensic corruption | Structured allow-listed metadata; redact tokens/raw files; encode untrusted values; length caps; separate secure log retention; never render audit metadata as HTML without escaping. [4] | Log redaction and injection tests. | Security owner / Low |
| `TM-25` | A support or break-glass operator accesses data silently or changes evidence while troubleshooting. | Operations | Insider misuse | Separate support role, time-bounded approval ticket, read-only default, explicit break-glass audit event before access, customer notification procedure, and no direct event mutation path. | Quarterly access review and simulated break-glass drill. | Operations owner / Medium |
| `TM-26` | Discard/retention process deletes a staged package but leaves report/audit references inconsistent, or retains data past policy. | Discard/retention | Integrity or privacy failure | State-based retention worker, legal-hold flag, tombstone/audit record, object-delete confirmation, report/audit retention separation, restore test. | Retention and restore drill. | Data owner / Medium |
| `TM-27` | Dependency, parser, container, or CI compromise changes validation behavior. | Build/deploy | Supply-chain compromise | Pinned dependencies, SBOM, signed build provenance, dependency scanning, isolated build, protected main branch, staged deploy, rollback, and regression suite on every release. | CI evidence and vulnerability response drill. | Engineering owner / Medium |
| `TM-28` | Customer assumes an integrity hash, report, or export is a certification, signature, or compliance attestation. | Product use | Misrepresentation and reliance risk | Product copy and API schema label digest limits; documented human approval boundary; customer onboarding review; no certification claims. | UX/copy review and pilot sponsor acknowledgment. | Product + quality / Low |

## Defense-in-depth control map

The control design does not rely on a single layer. File upload controls use type, signature, filename, size, storage, authorization, and scanning measures because OWASP recommends layered protections rather than trusting client content metadata. [3] API controls use TLS, validated sessions, per-object and per-function authorization, explicit state transitions, bounded inputs, safe errors, and security event logging. [4] The migration adds database-side tenant filtering and immutable evidence/audit tables as a further control layer.

| Layer | Mandatory control | Failure behavior |
|---|---|---|
| Edge | HTTPS, WAF/rate/quota controls, exact method/content-type allow-list, request IDs | Reject request before application work. |
| Identity | Validate token signature and claims; resolve active membership server-side | `401`/`403`, no batch existence disclosure. |
| API service | Object authorization, finite-state transition checks, idempotency reservation, `If-Match` preconditions | `404`, `409`, `410`, or controlled error envelope. |
| Staging storage | Opaque key, quarantine, immutable content digest, malware policy, no public read | Keep package unavailable; batch remains rejected/quarantined. |
| Worker | Bounded parsing and canonical validation; AUTH-HIST rules; report hash | Immutable rejected/validated report; no live writes. |
| Database | RLS, composite tenant FKs, state guard, append-only triggers, one apply transaction | Transaction rollback; no partial baseline. |
| Audit and recovery | Hash-chain audit events, centralized monitoring, backup/restore, retention worker | Detect, investigate, restore, and notify. |

## Security test plan and launch decision

Before a paid customer pilot, execute the following in a non-production environment: a cross-tenant endpoint matrix; RLS owner/role/bypass tests; role-suspension and policy-change-before-apply tests; all `AUTH-HIST` cases; concurrent apply/idempotency tests; package tamper/archive-bomb/traversal/unsafe-type tests; object-storage authorization tests; injected error/log redaction tests; database rollback after an induced mid-apply failure; audit-chain verification; and backup/restore from an encrypted backup.

The production decision is **no-go** when any High risk remains, when a Medium risk has no named owner or test evidence, or when a test demonstrates a cross-tenant read/write, an unauthorized human-only action, partial live import, mutable audit/ledger record, or undisclosed loss of backup completeness. PostgreSQL’s own RLS documentation notes that constraints may reveal existence information, so external API errors and import endpoint permissions must be designed to avoid turning uniqueness or foreign-key behavior into a tenant-enumeration channel. [1] [2]

## References

[1] [PostgreSQL, *Row Security Policies*](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)

[2] [PostgreSQL, *CREATE POLICY*](https://www.postgresql.org/docs/current/sql-createpolicy.html)

[3] [OWASP Cheat Sheet Series, *File Upload Cheat Sheet*](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)

[4] [OWASP Cheat Sheet Series, *REST Security Cheat Sheet*](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html)

[5] [OWASP API Security Project, *Top 10 API Security Risks—2023*](https://owasp.org/API-Security/editions/2023/en/0x11-t10/)
