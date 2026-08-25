# Earthward Evidence-Ledger TypeScript Client Contract

`src/imports.ts` is a dependency-free client contract for the future authenticated workspace import API. It intentionally provides both compile-time types and strict runtime parsers because API responses are untrusted input at a browser or integration boundary.

The canonical server contracts remain:

| Contract | Source |
|---|---|
| Import report | `schema/import-report.schema.json` |
| HTTP error envelope | `schema/api-error.schema.json` |
| HTTP paths and transport behavior | `services/traceability/openapi.workspace-import.yaml` |

Use `parseImportReport` before rendering validation findings or enabling an Apply action. The function rejects unsupported schema versions, missing/extra contract fields, invalid UUIDs/digests, invalid status relationships, and malformed `AUTH-HIST` findings. In particular, it refuses a report that says `validated` while also containing errors or blockers.

`WorkspaceImportClient` derives all authority from the caller’s workspace access token. It does not accept an organization ID, human identity, role, or source-provenance value as a client-supplied authority input.
