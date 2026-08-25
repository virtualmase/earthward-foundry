-- Earthward Evidence-Ledger workspace import storage.
--
-- Prerequisite: the foundational workspace migration has already created
-- organizations, organization_memberships, facilities, part_revisions,
-- part_units, ledger_events, attachments, and evidence_links as described in
-- docs/multitenant-workspace-design.md.
--
-- This migration intentionally stores staged package metadata and report data,
-- not raw customer ZIP bytes. Raw objects live in organization-prefixed object
-- storage and remain quarantined until the import worker marks them clean.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
  CREATE TYPE import_batch_state AS ENUM (
    'upload_pending', 'uploaded', 'validating', 'validated', 'rejected',
    'applying', 'applied', 'apply_failed', 'expired', 'discarded'
  );
EXCEPTION
  WHEN duplicate_object THEN NULL;
END;
$$;

DO $$
BEGIN
  CREATE TYPE import_mode AS ENUM ('sanitized_preflight', 'live_pre_acceptance_baseline');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END;
$$;

DO $$
BEGIN
  CREATE TYPE import_report_state AS ENUM ('validated', 'rejected', 'expired');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END;
$$;

DO $$
BEGIN
  CREATE TYPE import_finding_severity AS ENUM ('error', 'warning');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END;
$$;

DO $$
BEGIN
  CREATE TYPE import_package_state AS ENUM ('declared', 'quarantined', 'clean', 'rejected', 'purged');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END;
$$;

DO $$
BEGIN
  CREATE TYPE import_source_file_kind AS ENUM (
    'intake_manifest', 'part_revisions', 'part_units', 'ledger_events',
    'evidence_manifest', 'attachment', 'access_roster'
  );
EXCEPTION
  WHEN duplicate_object THEN NULL;
END;
$$;

DO $$
BEGIN
  CREATE TYPE import_mapping_kind AS ENUM (
    'part_revision', 'part_unit', 'ledger_event', 'attachment', 'evidence_link'
  );
EXCEPTION
  WHEN duplicate_object THEN NULL;
END;
$$;

DO $$
BEGIN
  CREATE TYPE import_apply_job_state AS ENUM ('queued', 'applying', 'applied', 'apply_failed');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END;
$$;

DO $$
BEGIN
  CREATE TYPE import_idempotency_operation AS ENUM ('create_batch', 'apply_batch');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END;
$$;

DO $$
BEGIN
  CREATE TYPE audit_outcome AS ENUM ('attempted', 'succeeded', 'failed', 'denied');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END;
$$;

CREATE TABLE import_batches (
  import_batch_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  facility_id UUID NOT NULL,
  mode import_mode NOT NULL,
  state import_batch_state NOT NULL DEFAULT 'upload_pending',
  submitted_by_membership_id UUID NOT NULL,
  declared_filename TEXT NOT NULL CHECK (declared_filename !~ '[/\\]' AND declared_filename ~ '\.zip$'),
  declared_byte_size BIGINT NOT NULL CHECK (declared_byte_size > 0 AND declared_byte_size <= 1073741824),
  package_sha256 CHAR(64) NOT NULL CHECK (package_sha256 ~ '^[a-f0-9]{64}$'),
  package_storage_key TEXT,
  package_state import_package_state NOT NULL DEFAULT 'declared',
  package_received_at TIMESTAMPTZ,
  package_quarantined_at TIMESTAMPTZ,
  package_clean_at TIMESTAMPTZ,
  policy_fingerprint CHAR(64) NOT NULL CHECK (policy_fingerprint ~ '^[a-f0-9]{64}$'),
  role_policy_version TEXT NOT NULL,
  report_expires_at TIMESTAMPTZ,
  applied_at TIMESTAMPTZ,
  applied_by_membership_id UUID,
  discarded_at TIMESTAMPTZ,
  discarded_by_membership_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY (organization_id, facility_id)
    REFERENCES facilities(organization_id, facility_id),
  FOREIGN KEY (organization_id, submitted_by_membership_id)
    REFERENCES organization_memberships(organization_id, membership_id),
  FOREIGN KEY (organization_id, applied_by_membership_id)
    REFERENCES organization_memberships(organization_id, membership_id),
  FOREIGN KEY (organization_id, discarded_by_membership_id)
    REFERENCES organization_memberships(organization_id, membership_id),
  UNIQUE (organization_id, import_batch_id),
  UNIQUE (organization_id, package_sha256),
  CHECK (
    (package_state = 'declared' AND package_storage_key IS NULL)
    OR (package_state IN ('quarantined', 'clean', 'rejected', 'purged') AND package_storage_key IS NOT NULL)
  ),
  CHECK (
    (state IN ('upload_pending', 'uploaded', 'validating') AND report_expires_at IS NULL)
    OR (state IN ('validated', 'rejected', 'applying', 'applied', 'apply_failed', 'expired') AND report_expires_at IS NOT NULL)
    OR state = 'discarded'
  )
);

CREATE TABLE import_source_files (
  import_source_file_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  import_batch_id UUID NOT NULL,
  file_kind import_source_file_kind NOT NULL,
  relative_path TEXT NOT NULL CHECK (relative_path !~ '(^/|\\|(^|/)\.\.(/|$))'),
  declared_sha256 CHAR(64) NOT NULL CHECK (declared_sha256 ~ '^[a-f0-9]{64}$'),
  observed_sha256 CHAR(64),
  byte_size BIGINT CHECK (byte_size >= 0),
  media_type TEXT,
  source_storage_key TEXT,
  scan_state import_package_state NOT NULL DEFAULT 'declared',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY (organization_id, import_batch_id)
    REFERENCES import_batches(organization_id, import_batch_id) ON DELETE RESTRICT,
  UNIQUE (organization_id, import_source_file_id),
  UNIQUE (organization_id, import_batch_id, relative_path),
  CHECK (observed_sha256 IS NULL OR observed_sha256 ~ '^[a-f0-9]{64}$')
);

CREATE TABLE import_reports (
  import_report_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  import_batch_id UUID NOT NULL,
  report_state import_report_state NOT NULL,
  validation_profile TEXT NOT NULL DEFAULT 'pre_acceptance_baseline_v1',
  package_sha256 CHAR(64) NOT NULL CHECK (package_sha256 ~ '^[a-f0-9]{64}$'),
  manifest_sha256 CHAR(64) NOT NULL CHECK (manifest_sha256 ~ '^[a-f0-9]{64}$'),
  policy_fingerprint CHAR(64) NOT NULL CHECK (policy_fingerprint ~ '^[a-f0-9]{64}$'),
  role_policy_version TEXT NOT NULL,
  source_file_count INTEGER NOT NULL CHECK (source_file_count >= 0),
  rows_examined INTEGER NOT NULL CHECK (rows_examined >= 0),
  rows_accepted INTEGER NOT NULL CHECK (rows_accepted >= 0),
  rows_rejected INTEGER NOT NULL CHECK (rows_rejected >= 0),
  error_count INTEGER NOT NULL CHECK (error_count >= 0),
  warning_count INTEGER NOT NULL CHECK (warning_count >= 0),
  proposed_record_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
  report_json JSONB NOT NULL,
  apply_precondition_sha256 CHAR(64) NOT NULL CHECK (apply_precondition_sha256 ~ '^[a-f0-9]{64}$'),
  report_integrity_sha256 CHAR(64) NOT NULL CHECK (report_integrity_sha256 ~ '^[a-f0-9]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  FOREIGN KEY (organization_id, import_batch_id)
    REFERENCES import_batches(organization_id, import_batch_id) ON DELETE RESTRICT,
  UNIQUE (organization_id, import_report_id),
  UNIQUE (organization_id, import_batch_id),
  CHECK (rows_accepted + rows_rejected <= rows_examined),
  CHECK (
    (report_state = 'validated' AND error_count = 0)
    OR (report_state = 'rejected' AND error_count > 0)
    OR report_state = 'expired'
  ),
  CHECK (expires_at > completed_at)
);

CREATE TABLE import_findings (
  import_finding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  import_report_id UUID NOT NULL,
  ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
  severity import_finding_severity NOT NULL,
  code TEXT NOT NULL CHECK (code ~ '^(PKG|SCHEMA|REF|EVENT|POLICY|EVIDENCE|IDEMP|AUTH)(-HIST)?-[0-9]{3}$'),
  message TEXT NOT NULL CHECK (length(message) <= 500),
  remediation TEXT NOT NULL CHECK (length(remediation) <= 1000),
  source_file TEXT,
  source_row INTEGER CHECK (source_row >= 2),
  source_column TEXT,
  source_key TEXT,
  event_type TEXT,
  rejected_action TEXT,
  related_source_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY (organization_id, import_report_id)
    REFERENCES import_reports(organization_id, import_report_id) ON DELETE RESTRICT,
  UNIQUE (organization_id, import_finding_id),
  UNIQUE (organization_id, import_report_id, ordinal),
  CHECK (
    code NOT IN ('AUTH-HIST-001', 'AUTH-HIST-002', 'AUTH-HIST-003', 'AUTH-HIST-004', 'AUTH-HIST-005', 'AUTH-HIST-006')
    OR (severity = 'error' AND source_file IS NOT NULL AND source_key IS NOT NULL)
  ),
  CHECK (
    code <> 'AUTH-HIST-001' OR (event_type = 'acceptance_decision' AND rejected_action = 'acceptance_decision')
  ),
  CHECK (
    code <> 'AUTH-HIST-002' OR (event_type = 'ncr_closed' AND rejected_action = 'ncr_closed')
  ),
  CHECK (
    code <> 'AUTH-HIST-003' OR (event_type = 'ncr_waived' AND rejected_action = 'ncr_waived')
  ),
  CHECK (
    code <> 'AUTH-HIST-004' OR (event_type = 'shipment' AND rejected_action = 'shipment')
  )
);

CREATE TABLE import_idempotency_keys (
  import_idempotency_key_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  membership_id UUID NOT NULL,
  operation import_idempotency_operation NOT NULL,
  idempotency_key UUID NOT NULL,
  request_sha256 CHAR(64) NOT NULL CHECK (request_sha256 ~ '^[a-f0-9]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  FOREIGN KEY (organization_id, membership_id)
    REFERENCES organization_memberships(organization_id, membership_id),
  UNIQUE (organization_id, import_idempotency_key_id),
  UNIQUE (organization_id, membership_id, operation, idempotency_key),
  CHECK (expires_at > created_at)
);

CREATE TABLE import_idempotency_responses (
  import_idempotency_response_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  import_idempotency_key_id UUID NOT NULL,
  http_status SMALLINT NOT NULL CHECK (http_status BETWEEN 100 AND 599),
  response_body JSONB NOT NULL,
  response_sha256 CHAR(64) NOT NULL CHECK (response_sha256 ~ '^[a-f0-9]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY (organization_id, import_idempotency_key_id)
    REFERENCES import_idempotency_keys(organization_id, import_idempotency_key_id) ON DELETE RESTRICT,
  UNIQUE (organization_id, import_idempotency_response_id),
  UNIQUE (organization_id, import_idempotency_key_id)
);

CREATE TABLE import_apply_jobs (
  import_apply_job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  import_batch_id UUID NOT NULL,
  import_report_id UUID NOT NULL,
  requested_by_membership_id UUID NOT NULL,
  idempotency_key_id UUID NOT NULL,
  state import_apply_job_state NOT NULL DEFAULT 'queued',
  package_sha256 CHAR(64) NOT NULL CHECK (package_sha256 ~ '^[a-f0-9]{64}$'),
  apply_precondition_sha256 CHAR(64) NOT NULL CHECK (apply_precondition_sha256 ~ '^[a-f0-9]{64}$'),
  policy_fingerprint CHAR(64) NOT NULL CHECK (policy_fingerprint ~ '^[a-f0-9]{64}$'),
  role_policy_version TEXT NOT NULL,
  failure_code TEXT,
  failure_request_id UUID,
  committed_record_counts JSONB,
  audit_event_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  FOREIGN KEY (organization_id, import_batch_id)
    REFERENCES import_batches(organization_id, import_batch_id) ON DELETE RESTRICT,
  FOREIGN KEY (organization_id, import_report_id)
    REFERENCES import_reports(organization_id, import_report_id) ON DELETE RESTRICT,
  FOREIGN KEY (organization_id, requested_by_membership_id)
    REFERENCES organization_memberships(organization_id, membership_id),
  FOREIGN KEY (organization_id, idempotency_key_id)
    REFERENCES import_idempotency_keys(organization_id, import_idempotency_key_id),
  UNIQUE (organization_id, import_apply_job_id),
  UNIQUE (organization_id, import_batch_id),
  UNIQUE (organization_id, idempotency_key_id),
  CHECK (
    (state IN ('queued', 'applying') AND completed_at IS NULL)
    OR (state IN ('applied', 'apply_failed') AND completed_at IS NOT NULL)
  )
);

CREATE TABLE import_source_key_mappings (
  import_source_key_mapping_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  import_batch_id UUID NOT NULL,
  import_apply_job_id UUID NOT NULL,
  mapping_kind import_mapping_kind NOT NULL,
  source_key TEXT NOT NULL,
  target_id UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY (organization_id, import_batch_id)
    REFERENCES import_batches(organization_id, import_batch_id) ON DELETE RESTRICT,
  FOREIGN KEY (organization_id, import_apply_job_id)
    REFERENCES import_apply_jobs(organization_id, import_apply_job_id) ON DELETE RESTRICT,
  UNIQUE (organization_id, import_source_key_mapping_id),
  UNIQUE (organization_id, import_batch_id, mapping_kind, source_key),
  UNIQUE (organization_id, mapping_kind, target_id)
);

CREATE TABLE audit_events (
  audit_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  audit_sequence BIGINT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor_membership_id UUID,
  actor_service_principal_id UUID,
  request_id UUID,
  event_type TEXT NOT NULL CHECK (event_type ~ '^[a-z0-9_]{3,100}$'),
  outcome audit_outcome NOT NULL,
  target_type TEXT NOT NULL CHECK (target_type ~ '^[a-z0-9_]{3,100}$'),
  target_id UUID,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  previous_event_sha256 CHAR(64),
  event_sha256 CHAR(64) NOT NULL CHECK (event_sha256 ~ '^[a-f0-9]{64}$'),
  FOREIGN KEY (organization_id, actor_membership_id)
    REFERENCES organization_memberships(organization_id, membership_id),
  FOREIGN KEY (organization_id, actor_service_principal_id)
    REFERENCES service_principals(organization_id, service_principal_id),
  CHECK (
    (actor_membership_id IS NOT NULL AND actor_service_principal_id IS NULL)
    OR (actor_membership_id IS NULL AND actor_service_principal_id IS NOT NULL)
    OR (actor_membership_id IS NULL AND actor_service_principal_id IS NULL)
  ),
  UNIQUE (organization_id, audit_event_id),
  UNIQUE (organization_id, audit_sequence),
  CHECK (previous_event_sha256 IS NULL OR previous_event_sha256 ~ '^[a-f0-9]{64}$')
);

CREATE INDEX idx_import_batches_org_state_created
  ON import_batches (organization_id, state, created_at DESC);
CREATE INDEX idx_import_batches_expiry
  ON import_batches (report_expires_at)
  WHERE state IN ('validated', 'rejected', 'applying');
CREATE INDEX idx_import_reports_org_batch
  ON import_reports (organization_id, import_batch_id, completed_at DESC);
CREATE INDEX idx_import_findings_org_report
  ON import_findings (organization_id, import_report_id, ordinal);
CREATE INDEX idx_import_apply_jobs_org_state_created
  ON import_apply_jobs (organization_id, state, created_at DESC);
CREATE INDEX idx_import_idempotency_expiry
  ON import_idempotency_keys (expires_at);
CREATE INDEX idx_audit_events_org_time
  ON audit_events (organization_id, occurred_at DESC, audit_sequence DESC);
CREATE INDEX idx_audit_events_target
  ON audit_events (organization_id, target_type, target_id, occurred_at DESC);

CREATE OR REPLACE FUNCTION workspace_import_batch_state_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.organization_id <> OLD.organization_id
     OR NEW.facility_id <> OLD.facility_id
     OR NEW.mode <> OLD.mode
     OR NEW.submitted_by_membership_id <> OLD.submitted_by_membership_id
     OR NEW.declared_filename <> OLD.declared_filename
     OR NEW.declared_byte_size <> OLD.declared_byte_size
     OR NEW.package_sha256 <> OLD.package_sha256
     OR NEW.policy_fingerprint <> OLD.policy_fingerprint
     OR NEW.role_policy_version <> OLD.role_policy_version
     OR NEW.created_at <> OLD.created_at THEN
    RAISE EXCEPTION 'import batch identity, declared package, and validation policy are immutable';
  END IF;

  IF NOT (
    (OLD.state = 'upload_pending' AND NEW.state IN ('upload_pending', 'uploaded', 'discarded', 'expired'))
    OR (OLD.state = 'uploaded' AND NEW.state IN ('uploaded', 'validating', 'discarded', 'expired'))
    OR (OLD.state = 'validating' AND NEW.state IN ('validating', 'validated', 'rejected', 'apply_failed', 'expired'))
    OR (OLD.state = 'validated' AND NEW.state IN ('validated', 'applying', 'discarded', 'expired'))
    OR (OLD.state = 'rejected' AND NEW.state IN ('rejected', 'discarded', 'expired'))
    OR (OLD.state = 'applying' AND NEW.state IN ('applying', 'applied', 'apply_failed'))
    OR (OLD.state IN ('applied', 'apply_failed', 'expired', 'discarded') AND NEW.state = OLD.state)
  ) THEN
    RAISE EXCEPTION 'invalid import batch state transition: % -> %', OLD.state, NEW.state;
  END IF;

  IF NOT (
    (OLD.package_state = 'declared' AND NEW.package_state IN ('declared', 'quarantined', 'rejected', 'purged'))
    OR (OLD.package_state = 'quarantined' AND NEW.package_state IN ('quarantined', 'clean', 'rejected', 'purged'))
    OR (OLD.package_state IN ('clean', 'rejected', 'purged') AND NEW.package_state = OLD.package_state)
  ) THEN
    RAISE EXCEPTION 'invalid import package state transition: % -> %', OLD.package_state, NEW.package_state;
  END IF;

  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

CREATE TRIGGER import_batches_state_guard
BEFORE UPDATE ON import_batches
FOR EACH ROW EXECUTE FUNCTION workspace_import_batch_state_guard();

CREATE OR REPLACE FUNCTION workspace_append_only_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION '% is append-only; create a new related record instead', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER import_source_files_append_only
BEFORE UPDATE OR DELETE ON import_source_files
FOR EACH ROW EXECUTE FUNCTION workspace_append_only_guard();

CREATE TRIGGER import_reports_append_only
BEFORE UPDATE OR DELETE ON import_reports
FOR EACH ROW EXECUTE FUNCTION workspace_append_only_guard();

CREATE TRIGGER import_findings_append_only
BEFORE UPDATE OR DELETE ON import_findings
FOR EACH ROW EXECUTE FUNCTION workspace_append_only_guard();

CREATE TRIGGER import_idempotency_keys_append_only
BEFORE UPDATE OR DELETE ON import_idempotency_keys
FOR EACH ROW EXECUTE FUNCTION workspace_append_only_guard();

CREATE TRIGGER import_idempotency_responses_append_only
BEFORE UPDATE OR DELETE ON import_idempotency_responses
FOR EACH ROW EXECUTE FUNCTION workspace_append_only_guard();

CREATE TRIGGER import_source_key_mappings_append_only
BEFORE UPDATE OR DELETE ON import_source_key_mappings
FOR EACH ROW EXECUTE FUNCTION workspace_append_only_guard();

CREATE TRIGGER audit_events_append_only
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION workspace_append_only_guard();

CREATE OR REPLACE FUNCTION workspace_assign_audit_chain()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  prior_hash CHAR(64);
  next_sequence BIGINT;
BEGIN
  -- Serialize only the per-organization chain; unrelated tenants remain concurrent.
  PERFORM pg_advisory_xact_lock(hashtextextended(NEW.organization_id::text, 0));

  SELECT audit_sequence, event_sha256
    INTO next_sequence, prior_hash
    FROM audit_events
   WHERE organization_id = NEW.organization_id
   ORDER BY audit_sequence DESC
   LIMIT 1;

  NEW.audit_sequence := COALESCE(next_sequence, 0) + 1;
  NEW.previous_event_sha256 := prior_hash;
  NEW.event_sha256 := encode(
    digest(
      concat_ws(
        '|',
        NEW.organization_id::text,
        NEW.audit_sequence::text,
        NEW.occurred_at::text,
        COALESCE(NEW.actor_membership_id::text, ''),
        COALESCE(NEW.actor_service_principal_id::text, ''),
        COALESCE(NEW.request_id::text, ''),
        NEW.event_type,
        NEW.outcome::text,
        NEW.target_type,
        COALESCE(NEW.target_id::text, ''),
        NEW.metadata::text,
        COALESCE(NEW.previous_event_sha256, '')
      ),
      'sha256'
    ),
    'hex'
  );
  RETURN NEW;
END;
$$;

CREATE TRIGGER audit_events_assign_chain
BEFORE INSERT ON audit_events
FOR EACH ROW EXECUTE FUNCTION workspace_assign_audit_chain();

COMMIT;
