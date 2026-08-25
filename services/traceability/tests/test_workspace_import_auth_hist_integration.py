"""Staging integration contract for pre-acceptance baseline-import rejection rules.

This suite intentionally skips unless it is pointed at a disposable workspace
environment. It is not a unit test for the current single-tenant Flask API,
which does not yet implement /v1/import-batches.

Required environment variables:
  EVIDENCE_LEDGER_IMPORT_TEST_BASE_URL   e.g. http://127.0.0.1:5010
  EVIDENCE_LEDGER_IMPORT_TEST_TOKEN      workspace session for a disposable org
  EVIDENCE_LEDGER_IMPORT_TEST_FACILITY   configured facility code, e.g. FAC-01

For non-local HTTP endpoints, explicitly set
EVIDENCE_LEDGER_IMPORT_ALLOW_NONLOCAL=true. Tests target a fresh, disposable
tenant because they create staged import records and archive test packages.

Run:
  python3 services/traceability/tests/test_workspace_import_auth_hist_integration.py
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from typing import Any


BASE_URL = os.environ.get("EVIDENCE_LEDGER_IMPORT_TEST_BASE_URL", "").rstrip("/")
TOKEN = os.environ.get("EVIDENCE_LEDGER_IMPORT_TEST_TOKEN", "")
FACILITY_CODE = os.environ.get("EVIDENCE_LEDGER_IMPORT_TEST_FACILITY", "FAC-01")
ALLOW_NONLOCAL = os.environ.get("EVIDENCE_LEDGER_IMPORT_ALLOW_NONLOCAL", "").lower() == "true"
POLL_TIMEOUT_SECONDS = float(os.environ.get("EVIDENCE_LEDGER_IMPORT_POLL_TIMEOUT_SECONDS", "30"))


@dataclass(frozen=True)
class AuthorityHistoryCase:
    code: str
    description: str
    target_event_type: str | None = None
    legacy_actor_claim: bool = False
    legacy_sod_claim: bool = False
    expected_location_file: str = "ledger_events.csv"


CASES = (
    AuthorityHistoryCase(
        "AUTH-HIST-001",
        "historical final acceptance must be rejected",
        target_event_type="acceptance_decision",
    ),
    AuthorityHistoryCase(
        "AUTH-HIST-002",
        "historical NCR closure must be rejected",
        target_event_type="ncr_closed",
    ),
    AuthorityHistoryCase(
        "AUTH-HIST-003",
        "historical NCR waiver must be rejected",
        target_event_type="ncr_waived",
    ),
    AuthorityHistoryCase(
        "AUTH-HIST-004",
        "historical shipment must be rejected",
        target_event_type="shipment",
    ),
    AuthorityHistoryCase(
        "AUTH-HIST-005",
        "provenance-to-membership reconciliation attempt must be rejected",
        legacy_actor_claim=True,
        expected_location_file="intake_manifest.json",
    ),
    AuthorityHistoryCase(
        "AUTH-HIST-006",
        "legacy material cannot satisfy separation of duties",
        legacy_sod_claim=True,
        expected_location_file="intake_manifest.json",
    ),
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _csv_bytes(headers: list[str], rows: list[list[str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _event_row(
    key: str,
    sequence: int,
    event_type: str,
    reference: str,
    payload: dict[str, Any] | None = None,
    corrects_key: str = "",
) -> list[str]:
    return [
        key,
        "UNIT-0001",
        str(sequence),
        f"2026-08-2{sequence}T14:30:00-07:00",
        event_type,
        reference,
        "human",
        "LEGACY-QUALITY-USER-01",
        corrects_key,
        json.dumps(payload or {}, sort_keys=True, separators=(",", ":")),
        "",
    ]


def build_authority_history_package(case: AuthorityHistoryCase) -> bytes:
    """Build a sanitized ZIP with exactly one intended AUTH-HIST violation.

    The test profile reserves `legacy_authority_claims` as an explicit negative
    test vector. Production intake packages must not use it. The importer must
    recognize the attempted reconciliation and emit AUTH-HIST-005 or
    AUTH-HIST-006 rather than silently treating the claim as a user/approval
    mapping or reducing it to an unrelated generic schema error.
    """

    part_revisions = _csv_bytes(
        [
            "source_part_revision_key",
            "part_number",
            "revision",
            "release_reference",
            "release_date",
            "facility_code",
        ],
        [["PART-REV-001", "PART-FAM-01", "A", "DRAWING-ALIAS-01", "2026-08-01", FACILITY_CODE]],
    )
    part_units = _csv_bytes(
        [
            "source_part_unit_key",
            "source_part_revision_key",
            "unit_identifier",
            "work_order_reference",
            "facility_code",
            "created_at",
        ],
        [["UNIT-0001", "PART-REV-001", "UNIT-ALIAS-0001", "WO-ALIAS-01", FACILITY_CODE, "2026-08-20T14:30:00-07:00"]],
    )

    event_headers = [
        "source_event_key",
        "source_part_unit_key",
        "sequence_hint",
        "occurred_at",
        "event_type",
        "reference",
        "source_provenance_type",
        "source_provenance_label",
        "corrects_source_event_key",
        "payload_json",
        "evidence_manifest_keys",
    ]
    event_rows = [_event_row("EVT-001", 1, "material_receipt", "CERT-ALIAS-01")]

    if case.target_event_type == "acceptance_decision":
        event_rows.extend(
            [
                _event_row("EVT-002", 2, "inspection_program_run", "PROGRAM-RUN-01"),
                _event_row(
                    "EVT-003",
                    3,
                    "inspection_result",
                    "INSP-RPT-01",
                    {"overall_result": "pass"},
                ),
                _event_row(
                    "EVT-004",
                    4,
                    "acceptance_decision",
                    "LEGACY-ACCEPTANCE-01",
                    {"decision": "accept"},
                ),
            ]
        )
    elif case.target_event_type in {"ncr_closed", "ncr_waived"}:
        event_rows.extend(
            [
                _event_row("EVT-002", 2, "ncr_opened", "NCR-ALIAS-01"),
                _event_row("EVT-003", 3, case.target_event_type, "NCR-DISPOSITION-ALIAS-01"),
            ]
        )
    elif case.target_event_type == "shipment":
        event_rows.extend(
            [
                _event_row("EVT-002", 2, "inspection_program_run", "PROGRAM-RUN-01"),
                _event_row(
                    "EVT-003",
                    3,
                    "inspection_result",
                    "INSP-RPT-01",
                    {"overall_result": "pass"},
                ),
                _event_row("EVT-004", 4, "shipment", "SHIPMENT-ALIAS-01"),
            ]
        )
    else:
        event_rows.extend(
            [
                _event_row("EVT-002", 2, "inspection_program_run", "PROGRAM-RUN-01"),
                _event_row(
                    "EVT-003",
                    3,
                    "inspection_result",
                    "INSP-RPT-01",
                    {"overall_result": "pass"},
                ),
            ]
        )

    ledger_events = _csv_bytes(event_headers, event_rows)
    evidence_manifest = _csv_bytes(
        [
            "evidence_manifest_key",
            "source_file_name",
            "sha256",
            "media_type",
            "byte_size",
            "storage_relative_path",
            "external_reference",
            "linked_source_event_keys",
        ],
        [],
    )

    source_files = {
        "part_revisions.csv": part_revisions,
        "part_units.csv": part_units,
        "ledger_events.csv": ledger_events,
        "evidence_manifest.csv": evidence_manifest,
    }
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "organization_alias": "INTEGRATION-TEST-ORG",
        "facility_code": FACILITY_CODE,
        "pilot_mode": "sanitized_preflight",
        "submitted_by_alias": "INTEGRATION-TESTER",
        "created_at": "2026-08-24T14:30:00-07:00",
        "source_files": [
            {"path": path, "sha256": _sha256(data)} for path, data in source_files.items()
        ],
    }
    if case.legacy_actor_claim:
        manifest["legacy_authority_claims"] = {
            "provenance_to_membership": [
                {
                    "source_provenance_label": "LEGACY-QUALITY-USER-01",
                    "target_membership_id": "11111111-1111-4111-8111-111111111111",
                    "requested_role": "quality_director",
                }
            ]
        }
    if case.legacy_sod_claim:
        manifest["legacy_authority_claims"] = {
            "separation_of_duties_satisfaction": [
                {
                    "part_unit_source_key": "UNIT-0001",
                    "inspection_source_event_key": "EVT-003",
                    "historical_reviewer_label": "LEGACY-QUALITY-USER-01",
                }
            ]
        }

    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr("intake_manifest.json", manifest_bytes)
        for path, data in source_files.items():
            output.writestr(path, data)
    return archive.getvalue()


class WorkspaceImportHttpClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.token = token

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        binary_body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], dict[str, Any] | None]:
        request_headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        request_headers.update(headers or {})
        body: bytes | None = None
        if json_body is not None:
            request_headers["Content-Type"] = "application/json"
            body = json.dumps(json_body).encode("utf-8")
        if binary_body is not None:
            body = binary_body
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers=request_headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read()
                return response.status, dict(response.headers.items()), json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            raw = error.read()
            payload = json.loads(raw) if raw else None
            return error.code, dict(error.headers.items()), payload

    def create_batch(self, package: bytes) -> str:
        status, _, payload = self.request(
            "POST",
            "/v1/import-batches",
            json_body={
                "mode": "sanitized_preflight",
                "facility_code": FACILITY_CODE,
                "source_package": {
                    "filename": "auth-history-test.zip",
                    "byte_size": len(package),
                    "sha256": _sha256(package),
                },
            },
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert status == 201, payload
        assert payload is not None
        return payload["import_batch_id"]

    def upload_package(self, batch_id: str, package: bytes) -> None:
        status, _, payload = self.request(
            "PUT",
            f"/v1/import-batches/{batch_id}/package",
            binary_body=package,
            headers={
                "Content-Type": "application/zip",
                "X-Content-SHA256": _sha256(package),
            },
        )
        assert status == 204, payload

    def start_dry_run(self, batch_id: str, package: bytes) -> None:
        status, _, payload = self.request(
            "POST",
            f"/v1/import-batches/{batch_id}/dry-run",
            headers={"If-Match": f'"{_sha256(package)}"'},
        )
        assert status == 202, payload

    def completed_report(self, batch_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            status, _, payload = self.request("GET", f"/v1/import-batches/{batch_id}/report")
            if status == 200:
                assert payload is not None
                return payload
            assert status == 409, payload
            time.sleep(0.25)
        raise AssertionError("Timed out waiting for completed dry-run import report")

    def apply_rejected_report(self, batch_id: str, report: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
        status, _, payload = self.request(
            "POST",
            f"/v1/import-batches/{batch_id}/apply",
            json_body={
                "report_id": report["report_id"],
                "confirmation": "APPLY PRE-ACCEPTANCE BASELINE",
            },
            headers={
                "Idempotency-Key": str(uuid.uuid4()),
                "If-Match": f'"{report["apply"]["apply_precondition_sha256"]}"',
            },
        )
        return status, payload

    def discard(self, batch_id: str) -> None:
        self.request("DELETE", f"/v1/import-batches/{batch_id}")


class WorkspaceImportAuthorityHistoryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not BASE_URL or not TOKEN:
            raise unittest.SkipTest(
                "Set EVIDENCE_LEDGER_IMPORT_TEST_BASE_URL and "
                "EVIDENCE_LEDGER_IMPORT_TEST_TOKEN to run workspace import integration tests."
            )
        parsed = urllib.parse.urlparse(BASE_URL)
        is_local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if parsed.scheme not in {"http", "https"}:
            raise unittest.SkipTest("Integration base URL must use http or https.")
        if not is_local and parsed.scheme != "https" and not ALLOW_NONLOCAL:
            raise unittest.SkipTest("Refusing non-local cleartext test target; use HTTPS or explicitly opt in.")
        cls.client = WorkspaceImportHttpClient(BASE_URL, TOKEN)

    def assert_authority_history_rejection(self, case: AuthorityHistoryCase) -> None:
        package = build_authority_history_package(case)
        batch_id = self.client.create_batch(package)
        try:
            self.client.upload_package(batch_id, package)
            self.client.start_dry_run(batch_id, package)
            report = self.client.completed_report(batch_id)

            self.assertEqual("earthward.evidence-ledger.import-report", report["report_type"])
            self.assertEqual("1.0", report["schema_version"])
            self.assertEqual("rejected", report["status"])
            self.assertFalse(report["apply"]["eligible"])
            self.assertIn(case.code, report["apply"]["blocked_by_codes"])
            self.assertGreaterEqual(report["summary"]["finding_counts"]["errors"], 1)

            findings = [finding for finding in report["findings"] if finding["code"] == case.code]
            self.assertEqual(1, len(findings), report["findings"])
            finding = findings[0]
            self.assertEqual("error", finding["severity"])
            self.assertIn(case.expected_location_file, finding["location"]["file"])
            self.assertIn("source_key", finding["location"])

            if case.target_event_type:
                self.assertEqual(case.target_event_type, finding["rejected_action"])
                self.assertEqual(case.target_event_type, finding["location"]["event_type"])
                rejected = {
                    item["event_type"]: item["count"]
                    for item in report["summary"]["rejected_authority_events"]
                }
                self.assertEqual(1, rejected[case.target_event_type])

            # A report with a blocking authority-history finding is never appliable.
            status, error = self.client.apply_rejected_report(batch_id, report)
            self.assertEqual(409, status, error)
            self.assertIsNotNone(error)
            self.assertEqual("IMPORT-APPLY-001", error["error"]["code"])
        finally:
            self.client.discard(batch_id)

    def test_auth_hist_001_rejects_historical_acceptance(self) -> None:
        self.assert_authority_history_rejection(CASES[0])

    def test_auth_hist_002_rejects_historical_ncr_closure(self) -> None:
        self.assert_authority_history_rejection(CASES[1])

    def test_auth_hist_003_rejects_historical_ncr_waiver(self) -> None:
        self.assert_authority_history_rejection(CASES[2])

    def test_auth_hist_004_rejects_historical_shipment(self) -> None:
        self.assert_authority_history_rejection(CASES[3])

    def test_auth_hist_005_rejects_historical_identity_reconciliation(self) -> None:
        self.assert_authority_history_rejection(CASES[4])

    def test_auth_hist_006_rejects_legacy_separation_of_duties_claim(self) -> None:
        self.assert_authority_history_rejection(CASES[5])


if __name__ == "__main__":
    unittest.main(verbosity=2)
