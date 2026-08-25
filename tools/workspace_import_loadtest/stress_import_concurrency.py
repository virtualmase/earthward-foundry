#!/usr/bin/env python3
"""Controlled concurrency checks for the Evidence-Ledger workspace import API.

This harness deliberately has no production-default target. It refuses a URL
unless it is localhost or explicitly named as staging, requires an operator
acknowledgement, never uploads a package, and discards every create-race batch
that it creates. The apply checks are more consequential: they require an
already validated *disposable* batch and an explicit acknowledgement because
exactly one request may cause a real baseline import.

The harness verifies HTTP/API behavior, not PostgreSQL internals. Run it against
a disposable staging workspace whose API points to the RLS migrations.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import statistics
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


STAGING_ACK = "I_AUTHORIZE_STAGING_IMPORT_LOAD"
DISPOSABLE_APPLY_ACK = "I_AUTHORIZE_ONE_DISPOSABLE_APPLY"
DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class HttpResult:
    ordinal: int
    status: int
    latency_ms: float
    body: dict[str, Any]
    error: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_json(value: bytes) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"_unparsed_body": value[:512].decode("utf-8", errors="replace")}
    return parsed if isinstance(parsed, dict) else {"_json_value": parsed}


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def require_safe_target(base_url: str, acknowledgement: str, allow_non_staging: bool) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("--base-url must be an absolute http(s) URL")
    staging_host = parsed.hostname in {"127.0.0.1", "localhost"} or "staging" in parsed.hostname
    if not staging_host and not allow_non_staging:
        raise ValueError(
            "target must be localhost or include 'staging' in its host; "
            "use --allow-non-staging only for an explicitly isolated test environment"
        )
    if acknowledgement != STAGING_ACK:
        raise ValueError(f"--acknowledge must equal {STAGING_ACK!r}")


class ImportApi:
    def __init__(self, base_url: str, token: str, timeout_seconds: float):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    def call(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        encoded_body = None if body is None else canonical_json(body).encode("utf-8")
        request_headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
            "X-Loadtest-Run": "workspace-import-concurrency",
        }
        if encoded_body is not None:
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        request = Request(
            url=f"{self.base_url}{path}",
            data=encoded_body,
            headers=request_headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return response.status, parse_json(response.read())
        except HTTPError as error:
            return error.code, parse_json(error.read())
        except URLError as error:
            return 0, {"error": {"code": "NETWORK-001", "message": str(error.reason)}}


def invoke_concurrently(
    workers: int,
    request_factory: Callable[[int], tuple[str, str, dict[str, Any] | None, dict[str, str] | None]],
    api: ImportApi,
) -> list[HttpResult]:
    barrier = threading.Barrier(workers)

    def invoke(ordinal: int) -> HttpResult:
        method, path, body, headers = request_factory(ordinal)
        try:
            barrier.wait(timeout=15)
            started = time.perf_counter()
            status, response_body = api.call(method, path, body=body, headers=headers)
            latency_ms = (time.perf_counter() - started) * 1000
            return HttpResult(ordinal, status, latency_ms, response_body)
        except Exception as error:  # Captured so all worker results are reported.
            return HttpResult(ordinal, 0, 0.0, {}, f"{type(error).__name__}: {error}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        return sorted(executor.map(invoke, range(workers)), key=lambda result: result.ordinal)


def response_error_code(result: HttpResult) -> str | None:
    value = result.body.get("error")
    return value.get("code") if isinstance(value, dict) else None


def summary(results: list[HttpResult]) -> dict[str, Any]:
    latencies = [result.latency_ms for result in results if result.latency_ms > 0]
    statuses: dict[str, int] = {}
    for result in results:
        statuses[str(result.status)] = statuses.get(str(result.status), 0) + 1
    return {
        "request_count": len(results),
        "status_counts": statuses,
        "network_or_worker_failures": sum(1 for result in results if result.status == 0),
        "latency_ms": {
            "min": round(min(latencies), 2) if latencies else None,
            "p50": round(statistics.median(latencies), 2) if latencies else None,
            "p95": round(percentile(latencies, 95), 2) if latencies else None,
            "max": round(max(latencies), 2) if latencies else None,
        },
    }


def percentile(values: list[float], percent: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * (percent / 100)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def create_declaration(facility_code: str, package_sha256: str, declared_size: int) -> dict[str, Any]:
    return {
        "mode": "sanitized_preflight",
        "facility_code": facility_code,
        "source_package": {
            "filename": "loadtest-declaration-only.zip",
            "byte_size": declared_size,
            "sha256": package_sha256,
        },
    }


def get_batch_id(result: HttpResult) -> str | None:
    value = result.body.get("import_batch_id")
    return value if isinstance(value, str) else None


def discard_batches(api: ImportApi, batch_ids: set[str]) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    for batch_id in sorted(batch_ids):
        status, body = api.call("DELETE", f"/v1/import-batches/{batch_id}")
        outcomes.append({"import_batch_id": batch_id, "status": status, "body": body})
    return outcomes


def create_replay_race(args: argparse.Namespace, api: ImportApi) -> dict[str, Any]:
    package_hash = sha256_text(f"{args.run_nonce}:replay-package")
    request_body = create_declaration(args.facility_code, package_hash, 4096)
    idempotency_key = str(uuid.uuid4())

    results = invoke_concurrently(
        args.workers,
        lambda _: (
            "POST",
            "/v1/import-batches",
            request_body,
            {"Idempotency-Key": idempotency_key},
        ),
        api,
    )
    ids = {batch_id for result in results if (batch_id := get_batch_id(result))}
    expected = all(result.status == 201 for result in results) and len(ids) == 1
    cleanup = discard_batches(api, ids) if args.cleanup else []
    return {
        "scenario": "create_replay_race",
        "expected": "all requests return the original 201 response with exactly one import_batch_id",
        "passed": expected,
        "idempotency_key": idempotency_key,
        "summary": summary(results),
        "distinct_import_batch_ids": sorted(ids),
        "cleanup": cleanup,
        "results": [asdict(result) for result in results],
    }


def create_unique_race(args: argparse.Namespace, api: ImportApi) -> dict[str, Any]:
    def request_factory(ordinal: int):
        package_hash = sha256_text(f"{args.run_nonce}:unique-package:{ordinal}")
        body = create_declaration(args.facility_code, package_hash, 4096 + ordinal)
        return "POST", "/v1/import-batches", body, {"Idempotency-Key": str(uuid.uuid4())}

    results = invoke_concurrently(args.workers, request_factory, api)
    ids = {batch_id for result in results if (batch_id := get_batch_id(result))}
    expected = all(result.status == 201 for result in results) and len(ids) == args.workers
    cleanup = discard_batches(api, ids) if args.cleanup else []
    return {
        "scenario": "create_unique_race",
        "expected": "each unique declaration creates one distinct upload_pending batch; no package bytes are uploaded",
        "passed": expected,
        "summary": summary(results),
        "distinct_import_batch_ids": sorted(ids),
        "cleanup": cleanup,
        "results": [asdict(result) for result in results],
    }


def apply_race(args: argparse.Namespace, api: ImportApi, *, same_key: bool) -> dict[str, Any]:
    if args.authorize_disposable_apply != DISPOSABLE_APPLY_ACK:
        raise ValueError(
            "apply checks require --authorize-disposable-apply "
            f"{DISPOSABLE_APPLY_ACK!r}; exactly one request can import a disposable baseline"
        )
    body = {
        "report_id": args.report_id,
        "confirmation": "APPLY PRE-ACCEPTANCE BASELINE",
    }
    replay_key = str(uuid.uuid4())

    def request_factory(_: int):
        key = replay_key if same_key else str(uuid.uuid4())
        return (
            "POST",
            f"/v1/import-batches/{args.batch_id}/apply",
            body,
            {"Idempotency-Key": key, "If-Match": f'"{args.apply_precondition_sha256}"'},
        )

    results = invoke_concurrently(args.workers, request_factory, api)
    job_ids = {
        result.body.get("apply_job_id")
        for result in results
        if isinstance(result.body.get("apply_job_id"), str)
    }
    if same_key:
        expected = all(result.status == 202 for result in results) and len(job_ids) == 1
        expectation = "matching apply retries return 202 with exactly one apply_job_id"
        scenario = "apply_replay_race"
    else:
        success_count = sum(1 for result in results if result.status == 202)
        conflict_count = sum(1 for result in results if result.status == 409)
        expected = success_count == 1 and conflict_count == args.workers - 1 and len(job_ids) == 1
        expectation = "one distinct idempotency key wins; all other concurrent apply keys receive 409"
        scenario = "apply_lock_contention_race"
    return {
        "scenario": scenario,
        "expected": expectation,
        "passed": expected,
        "summary": summary(results),
        "apply_job_ids": sorted(job_ids),
        "error_codes": sorted({code for result in results if (code := response_error_code(result))}),
        "results": [asdict(result) for result in results],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=["create-replay", "create-unique", "apply-replay", "apply-contention"])
    parser.add_argument("--base-url", required=True, help="Staging workspace API URL.")
    parser.add_argument("--token", default=os.environ.get("EVIDENCE_LEDGER_IMPORT_TEST_TOKEN"), help="Disposable staging token; defaults to EVIDENCE_LEDGER_IMPORT_TEST_TOKEN.")
    parser.add_argument("--facility-code", help="Active facility code; required for create scenarios.")
    parser.add_argument("--batch-id", help="Validated disposable batch; required for apply scenarios.")
    parser.add_argument("--report-id", help="Validated report ID; required for apply scenarios.")
    parser.add_argument("--apply-precondition-sha256", help="Report apply precondition digest; required for apply scenarios.")
    parser.add_argument("--workers", type=int, default=25, help="Concurrent requests (default: 25, max: 100).")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--acknowledge", required=True, help=f"Must equal {STAGING_ACK!r}.")
    parser.add_argument("--authorize-disposable-apply", help="Required only for apply scenarios.")
    parser.add_argument("--allow-non-staging", action="store_true", help="Allow an explicitly isolated test hostname that does not include 'staging'.")
    parser.add_argument("--no-cleanup", dest="cleanup", action="store_false", help="Do not discard create-race batches. Discouraged.")
    parser.add_argument("--output", type=Path, help="Write the full JSON result to this file.")
    parser.set_defaults(cleanup=True)
    args = parser.parse_args()
    if not args.token:
        parser.error("--token or EVIDENCE_LEDGER_IMPORT_TEST_TOKEN is required")
    if not 2 <= args.workers <= 100:
        parser.error("--workers must be between 2 and 100")
    if args.scenario.startswith("create") and not args.facility_code:
        parser.error("--facility-code is required for create scenarios")
    if args.scenario.startswith("apply"):
        missing = [
            name
            for name, value in {
                "--batch-id": args.batch_id,
                "--report-id": args.report_id,
                "--apply-precondition-sha256": args.apply_precondition_sha256,
            }.items()
            if not value
        ]
        if missing:
            parser.error(f"apply scenarios require {', '.join(missing)}")
        if len(args.apply_precondition_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in args.apply_precondition_sha256
        ):
            parser.error("--apply-precondition-sha256 must be a lowercase 64-character SHA-256 digest")
    return args


def main() -> int:
    args = parse_args()
    try:
        require_safe_target(args.base_url, args.acknowledge, args.allow_non_staging)
        api = ImportApi(args.base_url, args.token, args.timeout_seconds)
        args.run_nonce = str(uuid.uuid4())
        if args.scenario == "create-replay":
            report = create_replay_race(args, api)
        elif args.scenario == "create-unique":
            report = create_unique_race(args, api)
        elif args.scenario == "apply-replay":
            report = apply_race(args, api, same_key=True)
        else:
            report = apply_race(args, api, same_key=False)
    except (ValueError, RuntimeError) as error:
        report = {"passed": False, "configuration_error": str(error)}

    report["generated_at"] = utc_now()
    report["base_url"] = args.base_url
    report["workers"] = args.workers
    serialized = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
