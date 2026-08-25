-- Earthward Evidence-Ledger workspace import RLS and least-privilege grants.
--
-- Run after 20260825_001_workspace_import_storage.sql. The deployment role
-- executes migrations; it is not used by the HTTP application or background
-- worker. Application identities must use SET LOCAL inside a transaction, e.g.:
--   SELECT set_config('app.organization_id', '<uuid>', true);
--   SELECT set_config('app.membership_id', '<uuid>', true);
--
-- Treat these settings as trusted backend context only. They must be derived
-- from a validated session / queue job, never from a browser request field.

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'earthward_schema_owner') THEN
    CREATE ROLE earthward_schema_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'earthward_workspace_app') THEN
    CREATE ROLE earthward_workspace_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'earthward_import_worker') THEN
    CREATE ROLE earthward_import_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'earthward_workspace_readonly') THEN
    CREATE ROLE earthward_workspace_readonly NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
END;
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;

ALTER TABLE import_batches OWNER TO earthward_schema_owner;
ALTER TABLE import_source_files OWNER TO earthward_schema_owner;
ALTER TABLE import_reports OWNER TO earthward_schema_owner;
ALTER TABLE import_findings OWNER TO earthward_schema_owner;
ALTER TABLE import_idempotency_keys OWNER TO earthward_schema_owner;
ALTER TABLE import_idempotency_responses OWNER TO earthward_schema_owner;
ALTER TABLE import_apply_jobs OWNER TO earthward_schema_owner;
ALTER TABLE import_source_key_mappings OWNER TO earthward_schema_owner;
ALTER TABLE audit_events OWNER TO earthward_schema_owner;

CREATE OR REPLACE FUNCTION workspace_current_organization_id()
RETURNS UUID
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('app.organization_id', true), '')::uuid;
$$;

CREATE OR REPLACE FUNCTION workspace_current_membership_id()
RETURNS UUID
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('app.membership_id', true), '')::uuid;
$$;

CREATE OR REPLACE FUNCTION workspace_has_active_membership(expected_organization_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
      FROM organization_memberships m
     WHERE m.organization_id = expected_organization_id
       AND m.membership_id = workspace_current_membership_id()
       AND m.status = 'active'
  );
$$;

ALTER FUNCTION workspace_current_organization_id() OWNER TO earthward_schema_owner;
ALTER FUNCTION workspace_current_membership_id() OWNER TO earthward_schema_owner;
ALTER FUNCTION workspace_has_active_membership(UUID) OWNER TO earthward_schema_owner;

CREATE OR REPLACE FUNCTION workspace_append_audit_event(
  p_event_type TEXT,
  p_outcome audit_outcome,
  p_target_type TEXT,
  p_target_id UUID DEFAULT NULL,
  p_metadata JSONB DEFAULT '{}'::jsonb,
  p_request_id UUID DEFAULT NULL,
  p_actor_service_principal_id UUID DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_organization_id UUID := workspace_current_organization_id();
  v_membership_id UUID := workspace_current_membership_id();
  v_audit_event_id UUID;
BEGIN
  IF v_organization_id IS NULL OR NOT workspace_has_active_membership(v_organization_id) THEN
    RAISE EXCEPTION 'active organization membership is required to append an audit event';
  END IF;

  IF p_actor_service_principal_id IS NOT NULL THEN
    v_membership_id := NULL;
  END IF;

  INSERT INTO audit_events (
    organization_id,
    actor_membership_id,
    actor_service_principal_id,
    request_id,
    event_type,
    outcome,
    target_type,
    target_id,
    metadata
  ) VALUES (
    v_organization_id,
    v_membership_id,
    p_actor_service_principal_id,
    p_request_id,
    p_event_type,
    p_outcome,
    p_target_type,
    p_target_id,
    p_metadata
  ) RETURNING audit_event_id INTO v_audit_event_id;

  RETURN v_audit_event_id;
END;
$$;

ALTER FUNCTION workspace_append_audit_event(TEXT, audit_outcome, TEXT, UUID, JSONB, UUID, UUID)
  OWNER TO earthward_schema_owner;

-- Force RLS even when a migration/deployment role owns the table. The schema
-- owner should not be part of an application's connection role hierarchy.
ALTER TABLE import_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_batches FORCE ROW LEVEL SECURITY;
ALTER TABLE import_source_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_source_files FORCE ROW LEVEL SECURITY;
ALTER TABLE import_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_reports FORCE ROW LEVEL SECURITY;
ALTER TABLE import_findings ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_findings FORCE ROW LEVEL SECURITY;
ALTER TABLE import_idempotency_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_idempotency_keys FORCE ROW LEVEL SECURITY;
ALTER TABLE import_idempotency_responses ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_idempotency_responses FORCE ROW LEVEL SECURITY;
ALTER TABLE import_apply_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_apply_jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE import_source_key_mappings ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_source_key_mappings FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;

-- Browser-facing application role: read rows only within the organization in
-- the verified session. Mutations flow through reviewed service functions; do
-- not grant this role direct INSERT/UPDATE/DELETE on import/audit tables.
CREATE POLICY import_batches_app_select ON import_batches
  FOR SELECT TO earthward_workspace_app
  USING (
    organization_id = workspace_current_organization_id()
    AND workspace_has_active_membership(organization_id)
  );
CREATE POLICY import_source_files_app_select ON import_source_files
  FOR SELECT TO earthward_workspace_app
  USING (organization_id = workspace_current_organization_id() AND workspace_has_active_membership(organization_id));
CREATE POLICY import_reports_app_select ON import_reports
  FOR SELECT TO earthward_workspace_app
  USING (organization_id = workspace_current_organization_id() AND workspace_has_active_membership(organization_id));
CREATE POLICY import_findings_app_select ON import_findings
  FOR SELECT TO earthward_workspace_app
  USING (organization_id = workspace_current_organization_id() AND workspace_has_active_membership(organization_id));
CREATE POLICY import_idempotency_keys_app_select ON import_idempotency_keys
  FOR SELECT TO earthward_workspace_app
  USING (organization_id = workspace_current_organization_id() AND workspace_has_active_membership(organization_id));
CREATE POLICY import_idempotency_responses_app_select ON import_idempotency_responses
  FOR SELECT TO earthward_workspace_app
  USING (organization_id = workspace_current_organization_id() AND workspace_has_active_membership(organization_id));
CREATE POLICY import_apply_jobs_app_select ON import_apply_jobs
  FOR SELECT TO earthward_workspace_app
  USING (organization_id = workspace_current_organization_id() AND workspace_has_active_membership(organization_id));
CREATE POLICY import_source_key_mappings_app_select ON import_source_key_mappings
  FOR SELECT TO earthward_workspace_app
  USING (organization_id = workspace_current_organization_id() AND workspace_has_active_membership(organization_id));
CREATE POLICY audit_events_app_select ON audit_events
  FOR SELECT TO earthward_workspace_app
  USING (organization_id = workspace_current_organization_id() AND workspace_has_active_membership(organization_id));

-- Trusted background worker: it receives only an internal job carrying an
-- organization ID and acting membership, sets both values transaction-locally,
-- and is constrained to that organization by RLS. It has no BYPASSRLS grant.
CREATE POLICY import_batches_worker_tenant ON import_batches
  FOR ALL TO earthward_import_worker
  USING (organization_id = workspace_current_organization_id())
  WITH CHECK (organization_id = workspace_current_organization_id());
CREATE POLICY import_source_files_worker_tenant ON import_source_files
  FOR ALL TO earthward_import_worker
  USING (organization_id = workspace_current_organization_id())
  WITH CHECK (organization_id = workspace_current_organization_id());
CREATE POLICY import_reports_worker_tenant ON import_reports
  FOR ALL TO earthward_import_worker
  USING (organization_id = workspace_current_organization_id())
  WITH CHECK (organization_id = workspace_current_organization_id());
CREATE POLICY import_findings_worker_tenant ON import_findings
  FOR ALL TO earthward_import_worker
  USING (organization_id = workspace_current_organization_id())
  WITH CHECK (organization_id = workspace_current_organization_id());
CREATE POLICY import_idempotency_keys_worker_tenant ON import_idempotency_keys
  FOR SELECT TO earthward_import_worker
  USING (organization_id = workspace_current_organization_id());
CREATE POLICY import_idempotency_responses_worker_tenant ON import_idempotency_responses
  FOR SELECT TO earthward_import_worker
  USING (organization_id = workspace_current_organization_id());
CREATE POLICY import_apply_jobs_worker_tenant ON import_apply_jobs
  FOR ALL TO earthward_import_worker
  USING (organization_id = workspace_current_organization_id())
  WITH CHECK (organization_id = workspace_current_organization_id());
CREATE POLICY import_source_key_mappings_worker_tenant ON import_source_key_mappings
  FOR ALL TO earthward_import_worker
  USING (organization_id = workspace_current_organization_id())
  WITH CHECK (organization_id = workspace_current_organization_id());
CREATE POLICY audit_events_worker_select ON audit_events
  FOR SELECT TO earthward_import_worker
  USING (organization_id = workspace_current_organization_id());
-- `workspace_append_audit_event` runs as this owner and is the only runtime
-- insert path for audit rows. It remains bound to the same verified context
-- despite FORCE ROW LEVEL SECURITY.
CREATE POLICY audit_events_owner_append ON audit_events
  FOR INSERT TO earthward_schema_owner
  WITH CHECK (
    organization_id = workspace_current_organization_id()
    AND workspace_has_active_membership(organization_id)
  );

CREATE POLICY import_batches_readonly_select ON import_batches
  FOR SELECT TO earthward_workspace_readonly
  USING (organization_id = workspace_current_organization_id() AND workspace_has_active_membership(organization_id));
CREATE POLICY import_reports_readonly_select ON import_reports
  FOR SELECT TO earthward_workspace_readonly
  USING (organization_id = workspace_current_organization_id() AND workspace_has_active_membership(organization_id));
CREATE POLICY import_findings_readonly_select ON import_findings
  FOR SELECT TO earthward_workspace_readonly
  USING (organization_id = workspace_current_organization_id() AND workspace_has_active_membership(organization_id));
CREATE POLICY import_apply_jobs_readonly_select ON import_apply_jobs
  FOR SELECT TO earthward_workspace_readonly
  USING (organization_id = workspace_current_organization_id() AND workspace_has_active_membership(organization_id));
CREATE POLICY audit_events_readonly_select ON audit_events
  FOR SELECT TO earthward_workspace_readonly
  USING (organization_id = workspace_current_organization_id() AND workspace_has_active_membership(organization_id));

GRANT USAGE ON SCHEMA public TO earthward_workspace_app, earthward_import_worker, earthward_workspace_readonly;
GRANT SELECT ON import_batches, import_source_files, import_reports, import_findings,
  import_idempotency_keys, import_idempotency_responses, import_apply_jobs,
  import_source_key_mappings, audit_events TO earthward_workspace_app;
GRANT SELECT ON import_batches, import_reports, import_findings, import_apply_jobs,
  audit_events TO earthward_workspace_readonly;

GRANT SELECT, INSERT, UPDATE ON import_batches, import_source_files, import_reports,
  import_findings, import_apply_jobs, import_source_key_mappings TO earthward_import_worker;
GRANT SELECT ON import_idempotency_keys, import_idempotency_responses TO earthward_import_worker;
GRANT EXECUTE ON FUNCTION workspace_append_audit_event(TEXT, audit_outcome, TEXT, UUID, JSONB, UUID, UUID)
  TO earthward_workspace_app, earthward_import_worker;

REVOKE INSERT, UPDATE, DELETE ON audit_events FROM earthward_workspace_app, earthward_import_worker, earthward_workspace_readonly;
REVOKE UPDATE, DELETE ON import_source_files, import_reports, import_findings,
  import_idempotency_keys, import_idempotency_responses, import_source_key_mappings
  FROM earthward_workspace_app, earthward_import_worker, earthward_workspace_readonly;

COMMIT;
