/**
 * Evidence-Ledger workspace import client contract.
 *
 * Style: strict, dependency-free request and response validation. The server's
 * JSON Schemas remain authoritative; this module mirrors the import-report and
 * API-error contracts at the client boundary so an incompatible response is
 * rejected before a UI presents an unsafe Apply action.
 */

export type ImportMode = "sanitized_preflight" | "live_pre_acceptance_baseline";

export type ImportBatchState =
  | "upload_pending"
  | "uploaded"
  | "validating"
  | "validated"
  | "rejected"
  | "applying"
  | "applied"
  | "apply_failed"
  | "expired"
  | "discarded";

export type ImportReportStatus = "validated" | "rejected" | "expired";
export type FindingSeverity = "error" | "warning";

export type AuthorityEventType =
  | "acceptance_decision"
  | "ncr_closed"
  | "ncr_waived"
  | "shipment";

export type ValidationCode =
  | "PKG-001"
  | "PKG-002"
  | "SCHEMA-001"
  | "SCHEMA-002"
  | "REF-001"
  | "REF-002"
  | "EVENT-001"
  | "EVENT-002"
  | "POLICY-001"
  | "EVIDENCE-001"
  | "EVIDENCE-002"
  | "IDEMP-001"
  | "AUTH-001"
  | "AUTH-HIST-001"
  | "AUTH-HIST-002"
  | "AUTH-HIST-003"
  | "AUTH-HIST-004"
  | "AUTH-HIST-005"
  | "AUTH-HIST-006";

export type ApiErrorCode =
  | "AUTHENTICATION-001"
  | "AUTHORIZATION-001"
  | "IMPORT-BATCH-001"
  | "IMPORT-BATCH-002"
  | "IMPORT-BATCH-003"
  | "IMPORT-BATCH-004"
  | "IMPORT-BATCH-005"
  | "IMPORT-PACKAGE-001"
  | "IMPORT-PACKAGE-002"
  | "IMPORT-REPORT-001"
  | "IMPORT-APPLY-001"
  | "IMPORT-APPLY-002"
  | "RATE-LIMIT-001"
  | "INTERNAL-001";

export interface SourcePackageDeclaration {
  filename: string;
  byte_size: number;
  sha256: string;
}

export interface CreateImportBatchRequest {
  mode: ImportMode;
  facility_code: string;
  source_package: SourcePackageDeclaration;
}

export interface CreatedImportBatch {
  import_batch_id: string;
  state: "upload_pending";
  upload: {
    method: "PUT";
    path: string;
    expires_at: string;
    required_content_type: "application/zip";
    required_sha256: string;
  };
}

export interface ImportBatch {
  import_batch_id: string;
  state: ImportBatchState;
  mode: ImportMode;
  facility_code: string;
  created_at: string;
  report_id?: string | null;
  links: {
    self: string;
    report?: string | null;
    apply?: string | null;
  };
}

export interface ImportFindingLocation {
  file?: string;
  row?: number;
  column?: string;
  source_key?: string;
  event_type?: string;
}

export interface ImportFinding {
  severity: FindingSeverity;
  code: ValidationCode;
  message: string;
  remediation: string;
  location?: ImportFindingLocation;
  rejected_action?: AuthorityEventType;
  related_source_keys?: string[];
}

export interface ImportReport {
  report_type: "earthward.evidence-ledger.import-report";
  schema_version: "1.0";
  report_id: string;
  import_batch_id: string;
  organization_id: string;
  status: ImportReportStatus;
  mode: ImportMode;
  validation_profile: "pre_acceptance_baseline_v1";
  created_at: string;
  completed_at: string;
  source_package: {
    filename: string;
    byte_size: number;
    sha256: string;
    manifest_sha256: string;
    storage_state: "clean" | "quarantined" | "rejected";
  };
  submitted_by?: {
    membership_id: string;
    submitted_at: string;
  };
  summary: {
    source_file_count: number;
    rows_examined: number;
    rows_accepted: number;
    rows_rejected: number;
    finding_counts: { errors: number; warnings: number };
    proposed_records: {
      part_revisions: number;
      part_units: number;
      ledger_events: number;
      attachments: number;
      evidence_links: number;
    };
    rejected_authority_events: Array<{ event_type: AuthorityEventType; count: number }>;
  };
  findings: ImportFinding[];
  apply: {
    eligible: boolean;
    requires_explicit_confirmation: true;
    required_permission: "baseline_import.apply";
    blocked_by_codes: ValidationCode[];
    report_expires_at: string;
    apply_precondition_sha256: string;
  };
  integrity_sha256: string;
}

export interface ApplyImportRequest {
  report_id: string;
  confirmation: "APPLY PRE-ACCEPTANCE BASELINE";
}

export interface ApplyJobAccepted {
  apply_job_id: string;
  import_batch_id: string;
  state: "applying";
  status_path: string;
}

export interface ApplyJob {
  apply_job_id: string;
  import_batch_id: string;
  state: "applying" | "applied" | "apply_failed";
  created_at: string;
  completed_at?: string | null;
  audit_event_id?: string | null;
  committed_records?: {
    part_revisions: number;
    part_units: number;
    ledger_events: number;
    attachments: number;
    evidence_links: number;
  } | null;
}

export interface WorkspaceApiError {
  error: {
    code: ApiErrorCode;
    message: string;
    request_id: string;
    retryable: boolean;
    details?: Array<{ field: string; reason: string }>;
  };
}

export class ImportContractValidationError extends Error {
  public readonly path: string;

  public constructor(path: string, message: string) {
    super(`${path}: ${message}`);
    this.name = "ImportContractValidationError";
    this.path = path;
  }
}

export class WorkspaceImportApiError extends Error {
  public readonly status: number;
  public readonly response: WorkspaceApiError | undefined;

  public constructor(status: number, message: string, response?: WorkspaceApiError) {
    super(message);
    this.name = "WorkspaceImportApiError";
    this.status = status;
    this.response = response;
  }
}

type JsonRecord = Record<string, unknown>;
type FetchLike = typeof fetch;

const SHA256 = /^[a-f0-9]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const VALIDATION_CODES = new Set<ValidationCode>([
  "PKG-001", "PKG-002", "SCHEMA-001", "SCHEMA-002", "REF-001", "REF-002",
  "EVENT-001", "EVENT-002", "POLICY-001", "EVIDENCE-001", "EVIDENCE-002",
  "IDEMP-001", "AUTH-001", "AUTH-HIST-001", "AUTH-HIST-002", "AUTH-HIST-003",
  "AUTH-HIST-004", "AUTH-HIST-005", "AUTH-HIST-006",
]);
const API_ERROR_CODES = new Set<ApiErrorCode>([
  "AUTHENTICATION-001", "AUTHORIZATION-001", "IMPORT-BATCH-001", "IMPORT-BATCH-002",
  "IMPORT-BATCH-003", "IMPORT-BATCH-004", "IMPORT-BATCH-005", "IMPORT-PACKAGE-001",
  "IMPORT-PACKAGE-002", "IMPORT-REPORT-001", "IMPORT-APPLY-001", "IMPORT-APPLY-002",
  "RATE-LIMIT-001", "INTERNAL-001",
]);
const AUTHORITY_ACTION_BY_CODE: Partial<Record<ValidationCode, AuthorityEventType>> = {
  "AUTH-HIST-001": "acceptance_decision",
  "AUTH-HIST-002": "ncr_closed",
  "AUTH-HIST-003": "ncr_waived",
  "AUTH-HIST-004": "shipment",
};

function fail(path: string, message: string): never {
  throw new ImportContractValidationError(path, message);
}

function record(value: unknown, path: string): JsonRecord {
  if (value === null || typeof value !== "object" || Array.isArray(value)) fail(path, "must be an object");
  return value as JsonRecord;
}

function array(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) fail(path, "must be an array");
  return value;
}

function required(recordValue: JsonRecord, key: string, path: string): unknown {
  if (!(key in recordValue)) fail(path, `is missing required property ${key}`);
  return recordValue[key];
}

function string(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0) fail(path, "must be a non-empty string");
  return value;
}

function integer(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) fail(path, "must be a non-negative integer");
  return value;
}

function boolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") fail(path, "must be a boolean");
  return value;
}

function enumValue<T extends string>(value: unknown, values: readonly T[], path: string): T {
  if (typeof value !== "string" || !values.includes(value as T)) fail(path, `must be one of: ${values.join(", ")}`);
  return value as T;
}

function sha256(value: unknown, path: string): string {
  const parsed = string(value, path);
  if (!SHA256.test(parsed)) fail(path, "must be a lowercase 64-character SHA-256 hex digest");
  return parsed;
}

function uuid(value: unknown, path: string): string {
  const parsed = string(value, path);
  if (!UUID.test(parsed)) fail(path, "must be a UUID");
  return parsed;
}

function timestamp(value: unknown, path: string): string {
  const parsed = string(value, path);
  if (Number.isNaN(Date.parse(parsed))) fail(path, "must be an ISO 8601 date-time");
  return parsed;
}

function assertAllowedKeys(value: JsonRecord, allowed: readonly string[], path: string): void {
  for (const key of Object.keys(value)) {
    if (!allowed.includes(key)) fail(path, `contains unsupported property ${key}`);
  }
}

function isAuthorityCode(code: ValidationCode): code is keyof typeof AUTHORITY_ACTION_BY_CODE {
  return code in AUTHORITY_ACTION_BY_CODE || code === "AUTH-HIST-005" || code === "AUTH-HIST-006";
}

function parseFinding(value: unknown, path: string): ImportFinding {
  const item = record(value, path);
  assertAllowedKeys(item, ["severity", "code", "message", "remediation", "location", "rejected_action", "related_source_keys"], path);
  const severity = enumValue(required(item, "severity", path), ["error", "warning"] as const, `${path}.severity`);
  const rawCode = string(required(item, "code", path), `${path}.code`);
  if (!VALIDATION_CODES.has(rawCode as ValidationCode)) fail(`${path}.code`, "is not a supported validation code");
  const code = rawCode as ValidationCode;
  const finding: ImportFinding = {
    severity,
    code,
    message: string(required(item, "message", path), `${path}.message`),
    remediation: string(required(item, "remediation", path), `${path}.remediation`),
  };
  if (item.location !== undefined) {
    const location = record(item.location, `${path}.location`);
    assertAllowedKeys(location, ["file", "row", "column", "source_key", "event_type"], `${path}.location`);
    if (location.file !== undefined) string(location.file, `${path}.location.file`);
    if (location.row !== undefined && integer(location.row, `${path}.location.row`) < 2) fail(`${path}.location.row`, "must be at least 2");
    if (location.column !== undefined) string(location.column, `${path}.location.column`);
    if (location.source_key !== undefined) string(location.source_key, `${path}.location.source_key`);
    if (location.event_type !== undefined) string(location.event_type, `${path}.location.event_type`);
    finding.location = location as ImportFindingLocation;
  }
  if (item.rejected_action !== undefined) {
    finding.rejected_action = enumValue(item.rejected_action, ["acceptance_decision", "ncr_closed", "ncr_waived", "shipment"] as const, `${path}.rejected_action`);
  }
  if (item.related_source_keys !== undefined) {
    finding.related_source_keys = array(item.related_source_keys, `${path}.related_source_keys`).map((key, index) => string(key, `${path}.related_source_keys[${index}]`));
  }
  if (isAuthorityCode(code)) {
    if (finding.severity !== "error") fail(path, "AUTH-HIST findings must be errors");
    if (!finding.location?.file || !finding.location.source_key) fail(path, "AUTH-HIST findings must include location.file and location.source_key");
    const expectedAction = AUTHORITY_ACTION_BY_CODE[code];
    if (expectedAction && finding.rejected_action !== expectedAction) fail(path, `must reject ${expectedAction}`);
    if (expectedAction && finding.location.event_type !== expectedAction) fail(path, `must locate event type ${expectedAction}`);
  }
  return finding;
}

/** Parse and validate the canonical import report before presenting it to users. */
export function parseImportReport(value: unknown): ImportReport {
  const root = record(value, "import_report");
  assertAllowedKeys(root, [
    "report_type", "schema_version", "report_id", "import_batch_id", "organization_id", "status", "mode",
    "validation_profile", "created_at", "completed_at", "source_package", "submitted_by", "summary",
    "findings", "apply", "integrity_sha256",
  ], "import_report");
  if (required(root, "report_type", "import_report") !== "earthward.evidence-ledger.import-report") fail("import_report.report_type", "must be earthward.evidence-ledger.import-report");
  if (required(root, "schema_version", "import_report") !== "1.0") fail("import_report.schema_version", "must be 1.0");
  if (required(root, "validation_profile", "import_report") !== "pre_acceptance_baseline_v1") fail("import_report.validation_profile", "must be pre_acceptance_baseline_v1");

  const source = record(required(root, "source_package", "import_report"), "import_report.source_package");
  assertAllowedKeys(source, ["filename", "byte_size", "sha256", "manifest_sha256", "storage_state"], "import_report.source_package");
  const summary = record(required(root, "summary", "import_report"), "import_report.summary");
  assertAllowedKeys(summary, ["source_file_count", "rows_examined", "rows_accepted", "rows_rejected", "finding_counts", "proposed_records", "rejected_authority_events"], "import_report.summary");
  const findingCounts = record(required(summary, "finding_counts", "import_report.summary"), "import_report.summary.finding_counts");
  assertAllowedKeys(findingCounts, ["errors", "warnings"], "import_report.summary.finding_counts");
  const proposed = record(required(summary, "proposed_records", "import_report.summary"), "import_report.summary.proposed_records");
  assertAllowedKeys(proposed, ["part_revisions", "part_units", "ledger_events", "attachments", "evidence_links"], "import_report.summary.proposed_records");
  const rejectedAuthorityEvents = array(required(summary, "rejected_authority_events", "import_report.summary"), "import_report.summary.rejected_authority_events").map((item, index) => {
    const rejected = record(item, `import_report.summary.rejected_authority_events[${index}]`);
    assertAllowedKeys(rejected, ["event_type", "count"], `import_report.summary.rejected_authority_events[${index}]`);
    return {
      event_type: enumValue(required(rejected, "event_type", `import_report.summary.rejected_authority_events[${index}]`), ["acceptance_decision", "ncr_closed", "ncr_waived", "shipment"] as const, `import_report.summary.rejected_authority_events[${index}].event_type`),
      count: integer(required(rejected, "count", `import_report.summary.rejected_authority_events[${index}]`), `import_report.summary.rejected_authority_events[${index}].count`),
    };
  });
  const findings = array(required(root, "findings", "import_report"), "import_report.findings").map((item, index) => parseFinding(item, `import_report.findings[${index}]`));
  const apply = record(required(root, "apply", "import_report"), "import_report.apply");
  assertAllowedKeys(apply, ["eligible", "requires_explicit_confirmation", "required_permission", "blocked_by_codes", "report_expires_at", "apply_precondition_sha256"], "import_report.apply");
  const rawBlockedCodes = array(required(apply, "blocked_by_codes", "import_report.apply"), "import_report.apply.blocked_by_codes");
  const blockedByCodes = rawBlockedCodes.map((value, index) => {
    const code = string(value, `import_report.apply.blocked_by_codes[${index}]`) as ValidationCode;
    if (!VALIDATION_CODES.has(code)) fail(`import_report.apply.blocked_by_codes[${index}]`, "is not a supported validation code");
    return code;
  });
  if (new Set(blockedByCodes).size !== blockedByCodes.length) fail("import_report.apply.blocked_by_codes", "must not contain duplicates");

  const status = enumValue(required(root, "status", "import_report"), ["validated", "rejected", "expired"] as const, "import_report.status");
  const report: ImportReport = {
    report_type: "earthward.evidence-ledger.import-report",
    schema_version: "1.0",
    report_id: uuid(required(root, "report_id", "import_report"), "import_report.report_id"),
    import_batch_id: uuid(required(root, "import_batch_id", "import_report"), "import_report.import_batch_id"),
    organization_id: uuid(required(root, "organization_id", "import_report"), "import_report.organization_id"),
    status,
    mode: enumValue(required(root, "mode", "import_report"), ["sanitized_preflight", "live_pre_acceptance_baseline"] as const, "import_report.mode"),
    validation_profile: "pre_acceptance_baseline_v1",
    created_at: timestamp(required(root, "created_at", "import_report"), "import_report.created_at"),
    completed_at: timestamp(required(root, "completed_at", "import_report"), "import_report.completed_at"),
    source_package: {
      filename: string(required(source, "filename", "import_report.source_package"), "import_report.source_package.filename"),
      byte_size: integer(required(source, "byte_size", "import_report.source_package"), "import_report.source_package.byte_size"),
      sha256: sha256(required(source, "sha256", "import_report.source_package"), "import_report.source_package.sha256"),
      manifest_sha256: sha256(required(source, "manifest_sha256", "import_report.source_package"), "import_report.source_package.manifest_sha256"),
      storage_state: enumValue(required(source, "storage_state", "import_report.source_package"), ["clean", "quarantined", "rejected"] as const, "import_report.source_package.storage_state"),
    },
    summary: {
      source_file_count: integer(required(summary, "source_file_count", "import_report.summary"), "import_report.summary.source_file_count"),
      rows_examined: integer(required(summary, "rows_examined", "import_report.summary"), "import_report.summary.rows_examined"),
      rows_accepted: integer(required(summary, "rows_accepted", "import_report.summary"), "import_report.summary.rows_accepted"),
      rows_rejected: integer(required(summary, "rows_rejected", "import_report.summary"), "import_report.summary.rows_rejected"),
      finding_counts: {
        errors: integer(required(findingCounts, "errors", "import_report.summary.finding_counts"), "import_report.summary.finding_counts.errors"),
        warnings: integer(required(findingCounts, "warnings", "import_report.summary.finding_counts"), "import_report.summary.finding_counts.warnings"),
      },
      proposed_records: {
        part_revisions: integer(required(proposed, "part_revisions", "import_report.summary.proposed_records"), "import_report.summary.proposed_records.part_revisions"),
        part_units: integer(required(proposed, "part_units", "import_report.summary.proposed_records"), "import_report.summary.proposed_records.part_units"),
        ledger_events: integer(required(proposed, "ledger_events", "import_report.summary.proposed_records"), "import_report.summary.proposed_records.ledger_events"),
        attachments: integer(required(proposed, "attachments", "import_report.summary.proposed_records"), "import_report.summary.proposed_records.attachments"),
        evidence_links: integer(required(proposed, "evidence_links", "import_report.summary.proposed_records"), "import_report.summary.proposed_records.evidence_links"),
      },
      rejected_authority_events: rejectedAuthorityEvents,
    },
    findings,
    apply: {
      eligible: boolean(required(apply, "eligible", "import_report.apply"), "import_report.apply.eligible"),
      requires_explicit_confirmation: true,
      required_permission: "baseline_import.apply",
      blocked_by_codes: blockedByCodes,
      report_expires_at: timestamp(required(apply, "report_expires_at", "import_report.apply"), "import_report.apply.report_expires_at"),
      apply_precondition_sha256: sha256(required(apply, "apply_precondition_sha256", "import_report.apply"), "import_report.apply.apply_precondition_sha256"),
    },
    integrity_sha256: sha256(required(root, "integrity_sha256", "import_report"), "import_report.integrity_sha256"),
  };
  if (required(apply, "requires_explicit_confirmation", "import_report.apply") !== true) fail("import_report.apply.requires_explicit_confirmation", "must be true");
  if (required(apply, "required_permission", "import_report.apply") !== "baseline_import.apply") fail("import_report.apply.required_permission", "must be baseline_import.apply");
  if (status === "validated" && (report.summary.finding_counts.errors !== 0 || !report.apply.eligible || blockedByCodes.length !== 0)) fail("import_report", "validated report must have zero errors, no blockers, and be eligible");
  if (status === "rejected" && (report.summary.finding_counts.errors < 1 || report.apply.eligible)) fail("import_report", "rejected report must have errors and be ineligible");
  if (status === "expired" && report.apply.eligible) fail("import_report", "expired report must be ineligible");
  return report;
}

/** Validate a create-batch request before it is sent. */
export function assertCreateImportBatchRequest(value: CreateImportBatchRequest): void {
  const request = record(value, "create_import_batch_request");
  assertAllowedKeys(request, ["mode", "facility_code", "source_package"], "create_import_batch_request");
  enumValue(request.mode, ["sanitized_preflight", "live_pre_acceptance_baseline"] as const, "create_import_batch_request.mode");
  string(request.facility_code, "create_import_batch_request.facility_code");
  const source = record(request.source_package, "create_import_batch_request.source_package");
  assertAllowedKeys(source, ["filename", "byte_size", "sha256"], "create_import_batch_request.source_package");
  const filename = string(source.filename, "create_import_batch_request.source_package.filename");
  if (!/^[^/\\]+\.zip$/.test(filename)) fail("create_import_batch_request.source_package.filename", "must be a ZIP filename without path separators");
  if (integer(source.byte_size, "create_import_batch_request.source_package.byte_size") < 1) fail("create_import_batch_request.source_package.byte_size", "must be at least 1");
  sha256(source.sha256, "create_import_batch_request.source_package.sha256");
}

/** Validate the controlled Apply request before it is sent. */
export function assertApplyImportRequest(value: ApplyImportRequest): void {
  const request = record(value, "apply_import_request");
  assertAllowedKeys(request, ["report_id", "confirmation"], "apply_import_request");
  uuid(request.report_id, "apply_import_request.report_id");
  if (request.confirmation !== "APPLY PRE-ACCEPTANCE BASELINE") fail("apply_import_request.confirmation", "must match the required explicit confirmation text");
}

/** Format a SHA-256 digest as the strong ETag required by If-Match headers. */
export function strongEtag(sha256Digest: string): string {
  sha256(sha256Digest, "etag_sha256");
  return `"${sha256Digest}"`;
}

/** Parse the safe API error envelope returned for HTTP-layer failures. */
export function parseWorkspaceApiError(value: unknown): WorkspaceApiError {
  const root = record(value, "api_error");
  assertAllowedKeys(root, ["error"], "api_error");
  const error = record(required(root, "error", "api_error"), "api_error.error");
  assertAllowedKeys(error, ["code", "message", "request_id", "retryable", "details"], "api_error.error");
  const code = string(required(error, "code", "api_error.error"), "api_error.error.code") as ApiErrorCode;
  if (!API_ERROR_CODES.has(code)) fail("api_error.error.code", "is not a supported API error code");
  const parsed: WorkspaceApiError = {
    error: {
      code,
      message: string(required(error, "message", "api_error.error"), "api_error.error.message"),
      request_id: uuid(required(error, "request_id", "api_error.error"), "api_error.error.request_id"),
      retryable: boolean(required(error, "retryable", "api_error.error"), "api_error.error.retryable"),
    },
  };
  if (error.details !== undefined) {
    parsed.error.details = array(error.details, "api_error.error.details").map((detail, index) => {
      const item = record(detail, `api_error.error.details[${index}]`);
      assertAllowedKeys(item, ["field", "reason"], `api_error.error.details[${index}]`);
      return {
        field: string(required(item, "field", `api_error.error.details[${index}]`), `api_error.error.details[${index}].field`),
        reason: string(required(item, "reason", `api_error.error.details[${index}]`), `api_error.error.details[${index}].reason`),
      };
    });
  }
  return parsed;
}

function parseCreatedImportBatch(value: unknown): CreatedImportBatch {
  const root = record(value, "created_import_batch");
  assertAllowedKeys(root, ["import_batch_id", "state", "upload"], "created_import_batch");
  const upload = record(required(root, "upload", "created_import_batch"), "created_import_batch.upload");
  assertAllowedKeys(upload, ["method", "path", "expires_at", "required_content_type", "required_sha256"], "created_import_batch.upload");
  if (required(root, "state", "created_import_batch") !== "upload_pending") fail("created_import_batch.state", "must be upload_pending");
  if (required(upload, "method", "created_import_batch.upload") !== "PUT") fail("created_import_batch.upload.method", "must be PUT");
  if (required(upload, "required_content_type", "created_import_batch.upload") !== "application/zip") fail("created_import_batch.upload.required_content_type", "must be application/zip");
  return {
    import_batch_id: uuid(required(root, "import_batch_id", "created_import_batch"), "created_import_batch.import_batch_id"),
    state: "upload_pending",
    upload: {
      method: "PUT",
      path: string(required(upload, "path", "created_import_batch.upload"), "created_import_batch.upload.path"),
      expires_at: timestamp(required(upload, "expires_at", "created_import_batch.upload"), "created_import_batch.upload.expires_at"),
      required_content_type: "application/zip",
      required_sha256: sha256(required(upload, "required_sha256", "created_import_batch.upload"), "created_import_batch.upload.required_sha256"),
    },
  };
}

function parseImportBatch(value: unknown): ImportBatch {
  const root = record(value, "import_batch");
  assertAllowedKeys(root, ["import_batch_id", "state", "mode", "facility_code", "created_at", "report_id", "links"], "import_batch");
  const links = record(required(root, "links", "import_batch"), "import_batch.links");
  assertAllowedKeys(links, ["self", "report", "apply"], "import_batch.links");
  const batch: ImportBatch = {
    import_batch_id: uuid(required(root, "import_batch_id", "import_batch"), "import_batch.import_batch_id"),
    state: enumValue(required(root, "state", "import_batch"), ["upload_pending", "uploaded", "validating", "validated", "rejected", "applying", "applied", "apply_failed", "expired", "discarded"] as const, "import_batch.state"),
    mode: enumValue(required(root, "mode", "import_batch"), ["sanitized_preflight", "live_pre_acceptance_baseline"] as const, "import_batch.mode"),
    facility_code: string(required(root, "facility_code", "import_batch"), "import_batch.facility_code"),
    created_at: timestamp(required(root, "created_at", "import_batch"), "import_batch.created_at"),
    links: {
      self: string(required(links, "self", "import_batch.links"), "import_batch.links.self"),
    },
  };
  if (root.report_id !== undefined) {
    batch.report_id = root.report_id === null ? null : uuid(root.report_id, "import_batch.report_id");
  }
  if (links.report !== undefined) {
    batch.links.report = links.report === null ? null : string(links.report, "import_batch.links.report");
  }
  if (links.apply !== undefined) {
    batch.links.apply = links.apply === null ? null : string(links.apply, "import_batch.links.apply");
  }
  return batch;
}

function parseDryRunAccepted(value: unknown): { import_batch_id: string; state: "validating"; report_path: string } {
  const root = record(value, "dry_run_accepted");
  assertAllowedKeys(root, ["import_batch_id", "state", "report_path"], "dry_run_accepted");
  if (required(root, "state", "dry_run_accepted") !== "validating") fail("dry_run_accepted.state", "must be validating");
  return {
    import_batch_id: uuid(required(root, "import_batch_id", "dry_run_accepted"), "dry_run_accepted.import_batch_id"),
    state: "validating",
    report_path: string(required(root, "report_path", "dry_run_accepted"), "dry_run_accepted.report_path"),
  };
}

function parseApplyJobAccepted(value: unknown): ApplyJobAccepted {
  const root = record(value, "apply_job_accepted");
  assertAllowedKeys(root, ["apply_job_id", "import_batch_id", "state", "status_path"], "apply_job_accepted");
  if (required(root, "state", "apply_job_accepted") !== "applying") fail("apply_job_accepted.state", "must be applying");
  return {
    apply_job_id: uuid(required(root, "apply_job_id", "apply_job_accepted"), "apply_job_accepted.apply_job_id"),
    import_batch_id: uuid(required(root, "import_batch_id", "apply_job_accepted"), "apply_job_accepted.import_batch_id"),
    state: "applying",
    status_path: string(required(root, "status_path", "apply_job_accepted"), "apply_job_accepted.status_path"),
  };
}

function parseApplyJob(value: unknown): ApplyJob {
  const root = record(value, "apply_job");
  assertAllowedKeys(root, ["apply_job_id", "import_batch_id", "state", "created_at", "completed_at", "audit_event_id", "committed_records"], "apply_job");
  const state = enumValue(required(root, "state", "apply_job"), ["applying", "applied", "apply_failed"] as const, "apply_job.state");
  const job: ApplyJob = {
    apply_job_id: uuid(required(root, "apply_job_id", "apply_job"), "apply_job.apply_job_id"),
    import_batch_id: uuid(required(root, "import_batch_id", "apply_job"), "apply_job.import_batch_id"),
    state,
    created_at: timestamp(required(root, "created_at", "apply_job"), "apply_job.created_at"),
  };
  if (root.completed_at !== undefined && root.completed_at !== null) job.completed_at = timestamp(root.completed_at, "apply_job.completed_at");
  if (root.audit_event_id !== undefined && root.audit_event_id !== null) job.audit_event_id = uuid(root.audit_event_id, "apply_job.audit_event_id");
  if (root.committed_records !== undefined && root.committed_records !== null) {
    const records = record(root.committed_records, "apply_job.committed_records");
    assertAllowedKeys(records, ["part_revisions", "part_units", "ledger_events", "attachments", "evidence_links"], "apply_job.committed_records");
    job.committed_records = {
      part_revisions: integer(required(records, "part_revisions", "apply_job.committed_records"), "apply_job.committed_records.part_revisions"),
      part_units: integer(required(records, "part_units", "apply_job.committed_records"), "apply_job.committed_records.part_units"),
      ledger_events: integer(required(records, "ledger_events", "apply_job.committed_records"), "apply_job.committed_records.ledger_events"),
      attachments: integer(required(records, "attachments", "apply_job.committed_records"), "apply_job.committed_records.attachments"),
      evidence_links: integer(required(records, "evidence_links", "apply_job.committed_records"), "apply_job.committed_records.evidence_links"),
    };
  }
  return job;
}

export interface WorkspaceImportClientOptions {
  baseUrl: string;
  getAccessToken: () => Promise<string> | string;
  fetch?: FetchLike;
}

/**
 * Minimal browser/Node client for the staged import workflow. It has no side
 * channel to set organization or user identity; authentication is the only
 * authority input to the server.
 */
export class WorkspaceImportClient {
  private readonly baseUrl: string;
  private readonly getAccessToken: () => Promise<string> | string;
  private readonly fetchImpl: FetchLike;

  public constructor(options: WorkspaceImportClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.getAccessToken = options.getAccessToken;
    this.fetchImpl = options.fetch ?? fetch;
  }

  public async createBatch(request: CreateImportBatchRequest, idempotencyKey: string): Promise<CreatedImportBatch> {
    assertCreateImportBatchRequest(request);
    uuid(idempotencyKey, "idempotency_key");
    return parseCreatedImportBatch(await this.requestJson("POST", "/v1/import-batches", {
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(request),
    }));
  }

  public async uploadPackage(batchId: string, zipBody: BodyInit, sha256Digest: string): Promise<void> {
    uuid(batchId, "batch_id");
    sha256(sha256Digest, "package_sha256");
    await this.requestNoContent("PUT", `/v1/import-batches/${batchId}/package`, {
      headers: { "Content-Type": "application/zip", "X-Content-SHA256": sha256Digest },
      body: zipBody,
    });
  }

  public async startDryRun(batchId: string, packageDigest: string): Promise<{ import_batch_id: string; state: "validating"; report_path: string }> {
    uuid(batchId, "batch_id");
    return parseDryRunAccepted(await this.requestJson("POST", `/v1/import-batches/${batchId}/dry-run`, {
      headers: { "If-Match": strongEtag(packageDigest) },
    }));
  }

  public async getBatch(batchId: string): Promise<ImportBatch> {
    uuid(batchId, "batch_id");
    return parseImportBatch(await this.requestJson("GET", `/v1/import-batches/${batchId}`));
  }

  public async getReport(batchId: string): Promise<ImportReport> {
    uuid(batchId, "batch_id");
    return parseImportReport(await this.requestJson("GET", `/v1/import-batches/${batchId}/report`));
  }

  public async applyBatch(batchId: string, request: ApplyImportRequest, applyPreconditionDigest: string, idempotencyKey: string): Promise<ApplyJobAccepted> {
    uuid(batchId, "batch_id");
    assertApplyImportRequest(request);
    sha256(applyPreconditionDigest, "apply_precondition_sha256");
    uuid(idempotencyKey, "idempotency_key");
    return parseApplyJobAccepted(await this.requestJson("POST", `/v1/import-batches/${batchId}/apply`, {
      headers: {
        "Content-Type": "application/json",
        "If-Match": strongEtag(applyPreconditionDigest),
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify(request),
    }));
  }

  public async getApplyJob(batchId: string, jobId: string): Promise<ApplyJob> {
    uuid(batchId, "batch_id");
    uuid(jobId, "job_id");
    return parseApplyJob(await this.requestJson("GET", `/v1/import-batches/${batchId}/apply-jobs/${jobId}`));
  }

  public async discardBatch(batchId: string): Promise<void> {
    uuid(batchId, "batch_id");
    await this.requestNoContent("DELETE", `/v1/import-batches/${batchId}`);
  }

  private async requestJson(method: string, path: string, init: RequestInit = {}): Promise<unknown> {
    const response = await this.request(method, path, init);
    if (!response.ok) await this.throwApiError(response);
    if (response.status === 204) fail("response", "unexpected 204 response where JSON was required");
    return this.parseJson(response);
  }

  private async requestNoContent(method: string, path: string, init: RequestInit = {}): Promise<void> {
    const response = await this.request(method, path, init);
    if (!response.ok) await this.throwApiError(response);
    if (response.status !== 204) fail("response", `expected 204 response, received ${response.status}`);
  }

  private async request(method: string, path: string, init: RequestInit): Promise<Response> {
    const token = await this.getAccessToken();
    if (!token) fail("workspace_access_token", "must be non-empty");
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    headers.set("Authorization", `Bearer ${token}`);
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, { ...init, method, headers });
    return response;
  }

  private async parseJson(response: Response): Promise<unknown> {
    try {
      return await response.json();
    } catch {
      fail("response", "must contain valid JSON");
    }
  }

  private async throwApiError(response: Response): Promise<never> {
    let parsed: WorkspaceApiError | undefined;
    try {
      parsed = parseWorkspaceApiError(await response.json());
    } catch {
      // A non-conforming or empty error body is intentionally not trusted.
    }
    const message = parsed?.error.message ?? `Workspace import API request failed with HTTP ${response.status}`;
    throw new WorkspaceImportApiError(response.status, message, parsed);
  }
}
