"""Disposable local mock for AUTH-HIST integration-contract verification.

This server is intentionally narrow. It implements only the endpoints and
state transitions exercised by test_workspace_import_auth_hist_integration.py.
It does not model PostgreSQL, row-level security, attachment scanning, or any
customer-facing deployment control; use it only to verify the integration
suite's HTTP assertions and report-shape expectations before the workspace
service exists.

Run locally:
  WORKSPACE_IMPORT_MOCK_PORT=5010 python3 workspace_import_mock_server.py
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import Flask, jsonify, request


app = Flask(__name__)

ORGANIZATION_ID = "11111111-1111-4111-8111-111111111111"
BATCHES: dict[str, dict[str, Any]] = {}
AUTHORITY_CODES = {
    "acceptance_decision": "AUTH-HIST-001",
    "ncr_closed": "AUTH-HIST-002",
    "ncr_waived": "AUTH-HIST-003",
    "shipment": "AUTH-HIST-004",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def api_error(code: str, message: str, status: int):
    return (
        jsonify(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": str(uuid.uuid4()),
                    "retryable": False,
                }
            }
        ),
        status,
    )


def require_test_token():
    if request.headers.get("Authorization") != "Bearer local-test-token":
        return api_error("AUTHENTICATION-001", "A local test session is required.", 401)
    return None


def batch_or_404(batch_id: str):
    batch = BATCHES.get(batch_id)
    if not batch:
        return None, api_error("IMPORT-BATCH-003", "Import batch was not found.", 404)
    return batch, None


def finding(
    code: str,
    message: str,
    remediation: str,
    *,
    file: str,
    source_key: str,
    row: int,
    event_type: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "severity": "error",
        "code": code,
        "message": message,
        "remediation": remediation,
        "location": {
            "file": file,
            "row": row,
            "source_key": source_key,
        },
    }
    if event_type:
        result["location"]["column"] = "event_type"
        result["location"]["event_type"] = event_type
        result["rejected_action"] = event_type
    return result


def read_package(package_bytes: bytes) -> tuple[dict[str, Any], list[dict[str, str]]]:
    with zipfile.ZipFile(io.BytesIO(package_bytes)) as archive:
        manifest = json.loads(archive.read("intake_manifest.json"))
        event_text = archive.read("ledger_events.csv").decode("utf-8")
    return manifest, list(csv.DictReader(io.StringIO(event_text)))


def first_authority_finding(
    manifest: dict[str, Any], events: list[dict[str, str]]
) -> dict[str, Any] | None:
    claims = manifest.get("legacy_authority_claims")
    if isinstance(claims, dict) and claims.get("provenance_to_membership"):
        claim = claims["provenance_to_membership"][0]
        return finding(
            "AUTH-HIST-005",
            "Historical provenance cannot establish a current workspace membership or approval authority.",
            "Remove the mapping claim. Invite and activate the user through the workspace identity flow.",
            file="intake_manifest.json",
            source_key=str(claim.get("source_provenance_label", "UNKNOWN-LEGACY-ACTOR")),
            row=2,
        )
    if isinstance(claims, dict) and claims.get("separation_of_duties_satisfaction"):
        claim = claims["separation_of_duties_satisfaction"][0]
        return finding(
            "AUTH-HIST-006",
            "Legacy material cannot satisfy the independent current review required for final acceptance.",
            "Remove the claim and require an independent active human review when an acceptance decision is considered.",
            file="intake_manifest.json",
            source_key=str(claim.get("inspection_source_event_key", "UNKNOWN-LEGACY-EVENT")),
            row=2,
        )
    for row_number, event in enumerate(events, start=2):
        event_type = event["event_type"]
        if event_type in AUTHORITY_CODES:
            code = AUTHORITY_CODES[event_type]
            return finding(
                code,
                f"Historical {event_type} cannot be imported into a pre-acceptance baseline.",
                "Remove this row from the baseline and retain any historical document only as legacy evidence.",
                file="ledger_events.csv",
                source_key=event["source_event_key"],
                row=row_number,
                event_type=event_type,
            )
    return None


def report_for(batch: dict[str, Any]) -> dict[str, Any]:
    manifest, events = read_package(batch["package"])
    authority_finding = first_authority_finding(manifest, events)
    if not authority_finding:
        raise ValueError("Mock server expects a package that contains an AUTH-HIST negative test case")

    rejected_action = authority_finding.get("rejected_action")
    rejected_authority_events = (
        [{"event_type": rejected_action, "count": 1}] if rejected_action else []
    )
    report: dict[str, Any] = {
        "report_type": "earthward.evidence-ledger.import-report",
        "schema_version": "1.0",
        "report_id": str(uuid.uuid4()),
        "import_batch_id": batch["id"],
        "organization_id": ORGANIZATION_ID,
        "status": "rejected",
        "mode": batch["mode"],
        "validation_profile": "pre_acceptance_baseline_v1",
        "created_at": now(),
        "completed_at": now(),
        "source_package": {
            "filename": batch["filename"],
            "byte_size": len(batch["package"]),
            "sha256": batch["package_sha256"],
            "manifest_sha256": digest(manifest),
            "storage_state": "clean",
        },
        "submitted_by": {
            "membership_id": "22222222-2222-4222-8222-222222222222",
            "submitted_at": batch["created_at"],
        },
        "summary": {
            "source_file_count": 4,
            "rows_examined": len(events),
            "rows_accepted": max(0, len(events) - 1),
            "rows_rejected": 1,
            "finding_counts": {"errors": 1, "warnings": 0},
            "proposed_records": {
                "part_revisions": 1,
                "part_units": 1,
                "ledger_events": max(0, len(events) - 1),
                "attachments": 0,
                "evidence_links": 0,
            },
            "rejected_authority_events": rejected_authority_events,
        },
        "findings": [authority_finding],
        "apply": {
            "eligible": False,
            "requires_explicit_confirmation": True,
            "required_permission": "baseline_import.apply",
            "blocked_by_codes": [authority_finding["code"]],
            "report_expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
            "apply_precondition_sha256": "a" * 64,
        },
    }
    report["integrity_sha256"] = digest(report)
    return report


@app.post("/v1/import-batches")
def create_batch():
    auth_error = require_test_token()
    if auth_error:
        return auth_error
    body = request.get_json(force=True)
    package = body["source_package"]
    batch_id = str(uuid.uuid4())
    BATCHES[batch_id] = {
        "id": batch_id,
        "mode": body["mode"],
        "facility_code": body["facility_code"],
        "filename": package["filename"],
        "package_sha256": package["sha256"],
        "state": "upload_pending",
        "created_at": now(),
    }
    return jsonify(
        {
            "import_batch_id": batch_id,
            "state": "upload_pending",
            "upload": {
                "method": "PUT",
                "path": f"/v1/import-batches/{batch_id}/package",
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
                "required_content_type": "application/zip",
                "required_sha256": package["sha256"],
            },
        }
    ), 201


@app.put("/v1/import-batches/<batch_id>/package")
def upload_package(batch_id: str):
    auth_error = require_test_token()
    if auth_error:
        return auth_error
    batch, error = batch_or_404(batch_id)
    if error:
        return error
    if batch["state"] != "upload_pending":
        return api_error("IMPORT-BATCH-004", "Batch cannot accept another package.", 409)
    package = request.get_data()
    if request.content_type != "application/zip":
        return api_error("IMPORT-PACKAGE-001", "Package requires application/zip.", 415)
    if request.headers.get("X-Content-SHA256") != batch["package_sha256"]:
        return api_error("IMPORT-PACKAGE-001", "Package digest does not match declaration.", 400)
    if hashlib.sha256(package).hexdigest() != batch["package_sha256"]:
        return api_error("IMPORT-PACKAGE-001", "Package bytes do not match declaration.", 400)
    batch["package"] = package
    batch["state"] = "uploaded"
    return "", 204


@app.post("/v1/import-batches/<batch_id>/dry-run")
def dry_run(batch_id: str):
    auth_error = require_test_token()
    if auth_error:
        return auth_error
    batch, error = batch_or_404(batch_id)
    if error:
        return error
    if batch["state"] != "uploaded":
        return api_error("IMPORT-BATCH-004", "Batch is not ready for dry run.", 409)
    if request.headers.get("If-Match") != f'"{batch["package_sha256"]}"':
        return api_error("IMPORT-BATCH-004", "Package precondition does not match.", 409)
    batch["report"] = report_for(batch)
    batch["state"] = "rejected"
    return jsonify(
        {
            "import_batch_id": batch_id,
            "state": "validating",
            "report_path": f"/v1/import-batches/{batch_id}/report",
        }
    ), 202


@app.get("/v1/import-batches/<batch_id>/report")
def get_report(batch_id: str):
    auth_error = require_test_token()
    if auth_error:
        return auth_error
    batch, error = batch_or_404(batch_id)
    if error:
        return error
    if "report" not in batch:
        return api_error("IMPORT-REPORT-001", "Dry run is still in progress.", 409)
    return jsonify(batch["report"])


@app.post("/v1/import-batches/<batch_id>/apply")
def apply_batch(batch_id: str):
    auth_error = require_test_token()
    if auth_error:
        return auth_error
    batch, error = batch_or_404(batch_id)
    if error:
        return error
    if batch.get("report", {}).get("apply", {}).get("eligible") is not True:
        return api_error("IMPORT-APPLY-001", "The import report is not eligible for apply.", 409)
    return api_error("INTERNAL-001", "The local AUTH-HIST mock does not apply eligible batches.", 500)


@app.delete("/v1/import-batches/<batch_id>")
def discard_batch(batch_id: str):
    auth_error = require_test_token()
    if auth_error:
        return auth_error
    batch, error = batch_or_404(batch_id)
    if error:
        return error
    batch["state"] = "discarded"
    return "", 204


if __name__ == "__main__":
    port = int(os.environ.get("WORKSPACE_IMPORT_MOCK_PORT", "5010"))
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
