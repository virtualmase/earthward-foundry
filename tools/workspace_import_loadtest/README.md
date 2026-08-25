# Workspace Import Concurrency Harness

`stress_import_concurrency.py` stress-tests the future workspace import API’s **HTTP-visible idempotency and contention behavior**. It is intentionally a staging-only tool. It refuses a target host unless it is `localhost`, `127.0.0.1`, or contains `staging`, unless the operator explicitly overrides that check for an isolated environment. It never uploads ZIP bytes, and create-race scenarios discard every batch they create by default.

> **Do not run this against a customer or production workspace.** The apply scenarios can perform one real import of a validated disposable batch. Create a dedicated facility, tenant, package, and cleanup plan first.

## Preconditions

The target must implement the import API in `services/traceability/openapi.workspace-import.yaml`, use the RLS migrations, and expose a disposable test session with the required import permissions. Export the token only in the current terminal; do not place it in a command history, source file, or result artifact.

```bash
export EVIDENCE_LEDGER_IMPORT_TEST_TOKEN='<disposable-staging-token>'
ACK='I_AUTHORIZE_STAGING_IMPORT_LOAD'
BASE_URL='https://workspace-import.staging.example'
```

## Scenarios

| Scenario | What the harness sends | Expected proof | Data effect |
|---|---|---|---|
| `create-replay` | Concurrent identical `POST /v1/import-batches` requests with one idempotency key. | Every request returns the original `201` response and one batch ID. | Creates then discards one `upload_pending` batch. |
| `create-unique` | Concurrent batch declarations with unique keys and digests; no ZIP upload. | Every request creates a distinct `upload_pending` batch. | Creates then discards all batches. |
| `apply-replay` | Concurrent matching apply requests with one idempotency key. | Every request returns `202` and one apply-job ID. | Exactly one disposable baseline may be applied. |
| `apply-contention` | Concurrent apply requests with distinct idempotency keys for the same batch/report. | Exactly one `202`; all other requests return `409`; one job ID exists. | Exactly one disposable baseline may be applied. |

## Examples

Create idempotency replay race:

```bash
python3 stress_import_concurrency.py create-replay \
  --base-url "$BASE_URL" \
  --facility-code FAC-LOADTEST \
  --workers 50 \
  --acknowledge "$ACK" \
  --output ./artifacts/create-replay.json
```

Create distinct batch declarations and verify automatic cleanup:

```bash
python3 stress_import_concurrency.py create-unique \
  --base-url "$BASE_URL" \
  --facility-code FAC-LOADTEST \
  --workers 50 \
  --acknowledge "$ACK" \
  --output ./artifacts/create-unique.json
```

Run an apply replay check only after creating a **validated disposable** import batch. This operation requires a second acknowledgement because it can commit one baseline:

```bash
python3 stress_import_concurrency.py apply-replay \
  --base-url "$BASE_URL" \
  --batch-id '<disposable-batch-uuid>' \
  --report-id '<validated-report-uuid>' \
  --apply-precondition-sha256 '<64-lowercase-hex>' \
  --workers 25 \
  --acknowledge "$ACK" \
  --authorize-disposable-apply 'I_AUTHORIZE_ONE_DISPOSABLE_APPLY' \
  --output ./artifacts/apply-replay.json
```

## Acceptance and cleanup

Treat `passed: true` as an API-level concurrency signal, not as proof that the database lock implementation is adequate at arbitrary load. Archive the full JSON result, API/worker metrics, database lock wait metrics, and audit events for each run. The test must be followed by a cleanup assertion: created batches are `discarded`; the one authorized apply has exactly one import audit event; and no unexpected part, attachment, mapping, or apply-job count exists in the disposable tenant.
