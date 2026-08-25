# Evidence-Ledger Workspace: Multi-Tenant Data and Permission Design

## Decision

Use **PostgreSQL** as the system of record for the customer-facing workspace. The current SQLite ledger remains a valuable single-tenant proof loop, but a paid workspace needs database-enforced tenant separation, durable user attribution, backup controls, and transaction semantics across records, approvals, and evidence. The application should not rely on client-provided `source` values as identity; every write derives its actor from the authenticated session, membership, or scoped service credential.

> **Invariant:** Every customer-owned row carries `organization_id`, every request executes with a verified active membership, and no runtime role can update or delete an existing ledger event.

## Tenant boundary and identity model

An **organization** is the billable customer boundary. A **facility** is an optional operating location inside that organization. A user can belong to more than one organization, but each request is scoped to exactly one active organization. A part, evidence object, export, integration, and event belong to one organization only.

| Entity | Purpose | Critical constraint |
|---|---|---|
| `users` | Global identity linked to the identity provider subject | No organization data belongs here. |
| `organizations` | Customer/legal and billing boundary | Never infer this from email domain. |
| `organization_memberships` | A user’s active role inside one organization | `UNIQUE (organization_id, user_id)` prevents ambiguous membership. |
| `facilities` | Optional internal operational boundary | A facility cannot cross organizations. |
| `service_principals` | Scoped machine/integration identity | Secret is stored only as a hash; credentials never authorize human-only decisions. |
| `part_revisions` | Released part number and revision | `UNIQUE (organization_id, part_number, revision)`. |
| `part_units` | The serialized, lot, or work-order-level subject of an evidence ledger | Cannot reference a revision or facility outside its organization. |
| `ledger_events` | Immutable evidence history | Insert only; no runtime update or delete grant. |
| `attachments` | Content-addressed external evidence metadata | Object storage path is organization-prefixed; SHA-256 required. |
| `evidence_links` | Connects an event to a document, measurement report, or outside reference | Cannot join rows from different organizations. |
| `approval_policies` | Which role is authorized to complete high-consequence actions | Human-only decisions are enforced here and in application logic. |
| `evidence_exports` | Immutable export manifest and digest | Export creation is auditable; a digest is not a signature. |
| `audit_log` | Security and configuration audit trail | Append only; separate from the part evidence ledger. |

## PostgreSQL schema skeleton

The production migration should use a migration tool, tested DDL, and a dedicated application database role. The following skeleton establishes the required shapes and constraints; enumerations can be converted to controlled lookup tables if customer-specific workflows require extension.

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE membership_role AS ENUM (
  'organization_owner', 'organization_admin', 'quality_director',
  'quality_engineer', 'manufacturing_engineer', 'inspector',
  'traceability_specialist', 'operator', 'auditor', 'integration_service'
);

CREATE TYPE actor_kind AS ENUM ('human', 'service');
CREATE TYPE membership_status AS ENUM ('invited', 'active', 'suspended', 'removed');
CREATE TYPE evidence_export_status AS ENUM ('created', 'downloaded', 'expired', 'revoked');

CREATE TABLE users (
  user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  identity_subject TEXT NOT NULL UNIQUE,
  email TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  disabled_at TIMESTAMPTZ
);

CREATE TABLE organizations (
  organization_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT NOT NULL UNIQUE,
  legal_name TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('trial', 'active', 'suspended', 'closed')),
  data_region TEXT NOT NULL DEFAULT 'us-central1',
  retention_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at TIMESTAMPTZ
);

CREATE TABLE organization_memberships (
  membership_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  user_id UUID NOT NULL REFERENCES users(user_id),
  role membership_role NOT NULL,
  status membership_status NOT NULL DEFAULT 'invited',
  invited_by_membership_id UUID,
  accepted_at TIMESTAMPTZ,
  suspended_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (organization_id, user_id)
);

CREATE TABLE facilities (
  facility_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  name TEXT NOT NULL,
  external_code TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (organization_id, facility_id),
  UNIQUE (organization_id, name)
);

CREATE TABLE part_revisions (
  part_revision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  part_number TEXT NOT NULL,
  revision TEXT NOT NULL,
  release_reference TEXT NOT NULL,
  released_by_membership_id UUID REFERENCES organization_memberships(membership_id),
  released_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (organization_id, part_revision_id),
  UNIQUE (organization_id, part_number, revision)
);

CREATE TABLE part_units (
  part_unit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  part_revision_id UUID NOT NULL,
  facility_id UUID,
  unit_identifier TEXT NOT NULL,
  work_order_reference TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY (organization_id, part_revision_id)
    REFERENCES part_revisions(organization_id, part_revision_id),
  FOREIGN KEY (organization_id, facility_id)
    REFERENCES facilities(organization_id, facility_id),
  UNIQUE (organization_id, part_unit_id),
  UNIQUE (organization_id, unit_identifier)
);

CREATE TABLE service_principals (
  service_principal_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  name TEXT NOT NULL,
  credential_hash TEXT NOT NULL UNIQUE,
  allowed_event_types TEXT[] NOT NULL,
  expires_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (organization_id, service_principal_id),
  UNIQUE (organization_id, name)
);

CREATE TABLE ledger_events (
  ledger_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  part_unit_id UUID NOT NULL,
  sequence_number BIGINT NOT NULL,
  event_type TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor_kind actor_kind NOT NULL,
  actor_membership_id UUID,
  actor_service_principal_id UUID,
  reference TEXT NOT NULL,
  corrects_ledger_event_id UUID,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  payload_sha256 CHAR(64) NOT NULL,
  FOREIGN KEY (organization_id, part_unit_id)
    REFERENCES part_units(organization_id, part_unit_id),
  FOREIGN KEY (organization_id, actor_membership_id)
    REFERENCES organization_memberships(organization_id, membership_id),
  FOREIGN KEY (organization_id, actor_service_principal_id)
    REFERENCES service_principals(organization_id, service_principal_id),
  FOREIGN KEY (corrects_ledger_event_id) REFERENCES ledger_events(ledger_event_id),
  CHECK ((actor_kind = 'human' AND actor_membership_id IS NOT NULL
          AND actor_service_principal_id IS NULL)
      OR (actor_kind = 'service' AND actor_service_principal_id IS NOT NULL
          AND actor_membership_id IS NULL)),
  UNIQUE (organization_id, ledger_event_id),
  UNIQUE (organization_id, part_unit_id, sequence_number)
);

CREATE TABLE attachments (
  attachment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  storage_key TEXT NOT NULL,
  filename TEXT NOT NULL,
  media_type TEXT NOT NULL,
  byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
  sha256 CHAR(64) NOT NULL,
  uploaded_by_membership_id UUID NOT NULL,
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY (organization_id, uploaded_by_membership_id)
    REFERENCES organization_memberships(organization_id, membership_id),
  UNIQUE (organization_id, attachment_id),
  UNIQUE (organization_id, storage_key)
);

CREATE TABLE evidence_links (
  evidence_link_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  ledger_event_id UUID NOT NULL,
  attachment_id UUID,
  external_reference TEXT,
  linked_by_membership_id UUID NOT NULL,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY (organization_id, ledger_event_id)
    REFERENCES ledger_events(organization_id, ledger_event_id),
  FOREIGN KEY (organization_id, attachment_id)
    REFERENCES attachments(organization_id, attachment_id),
  FOREIGN KEY (organization_id, linked_by_membership_id)
    REFERENCES organization_memberships(organization_id, membership_id),
  CHECK (attachment_id IS NOT NULL OR external_reference IS NOT NULL)
);

CREATE TABLE evidence_exports (
  evidence_export_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(organization_id),
  part_unit_id UUID NOT NULL,
  requested_by_membership_id UUID NOT NULL,
  manifest_sha256 CHAR(64) NOT NULL,
  storage_key TEXT NOT NULL,
  status evidence_export_status NOT NULL DEFAULT 'created',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ,
  FOREIGN KEY (organization_id, part_unit_id)
    REFERENCES part_units(organization_id, part_unit_id),
  FOREIGN KEY (organization_id, requested_by_membership_id)
    REFERENCES organization_memberships(organization_id, membership_id),
  UNIQUE (organization_id, evidence_export_id)
);

CREATE INDEX idx_part_units_org_revision ON part_units (organization_id, part_revision_id);
CREATE INDEX idx_ledger_events_org_part_time
  ON ledger_events (organization_id, part_unit_id, occurred_at, recorded_at);
CREATE INDEX idx_evidence_links_org_event ON evidence_links (organization_id, ledger_event_id);
```

## Append-only and approval enforcement

The service-layer sequencing logic remains valuable, but production enforcement needs a second line of defense in the database. The application database role receives `SELECT` and `INSERT` on `ledger_events`; it does **not** receive `UPDATE` or `DELETE`. A trigger rejects all modifications or removals, including by a mistakenly privileged migration role unless migrations explicitly disable it in a controlled maintenance window.

```sql
CREATE FUNCTION reject_ledger_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'ledger_events are append-only; create a correction event instead';
END;
$$;

CREATE TRIGGER ledger_events_no_update
BEFORE UPDATE OR DELETE ON ledger_events
FOR EACH ROW EXECUTE FUNCTION reject_ledger_mutation();

REVOKE UPDATE, DELETE ON ledger_events FROM earthward_app;
```

Human-only decisions are checked in both the application and a database function that resolves the actor’s active role. The policy applies to `acceptance_decision`, `ncr_closed`, and `ncr_waived`. A service principal may never write those event types, even if its credential is otherwise valid.

## Organization-scoped role permissions

The application should use explicit permission codes rather than scattered role-name checks. Roles map to permissions centrally, and every authorization decision records the authenticated membership ID.

| Role | Main permissions | Explicitly excluded |
|---|---|---|
| **Organization Owner** | Billing, organization closure, ownership transfer, designate administrators | Cannot alter or erase ledger events; does not gain quality approval automatically. |
| **Organization Admin** | Invite/suspend members, facilities, integration configuration, read/export records | Cannot accept parts, close or waive NCRs, or alter history. |
| **Quality Director** | All read/export rights; write quality evidence; open NCR; close/waive NCR; record acceptance/rejection; manage approval policy | Cannot edit/delete historical events. |
| **Quality Engineer** | Read/export; write quality evidence; open NCR; draft disposition; recommend acceptance | Cannot record final acceptance/rejection, close/waive an NCR, or manage memberships. |
| **Manufacturing Engineer** | Read/export; create part revisions; record process-plan and process-step evidence; open deviation | Cannot record inspection result, final acceptance, NCR closure/waiver, or modify history. |
| **Inspector** | Read assigned records; log inspection-program and inspection-result events; attach reports | Cannot release part revisions, accept/reject, or close/waive NCRs. |
| **Traceability Specialist** | Read/export; attach and link evidence; create correction requests; maintain record completeness | Cannot write quality decisions or modify events. |
| **Operator** | Read assigned part units; log material receipt and process completion | Cannot write inspection, NCR disposition, acceptance, or configuration. |
| **Auditor** | Read and export all in-scope records and audit manifests | Read-only. |
| **Integration Service** | Only API-scope-allowlisted low-risk event types, e.g. inspection result or material receipt | Never a human approval, never membership/configuration access, never a cross-organization query. |

## Row-level security

Enable PostgreSQL RLS on every organization-owned table. At transaction start, the backend sets both `app.organization_id` and `app.membership_id` from verified identity claims; neither value comes from a request body, URL segment, or browser storage.

```sql
ALTER TABLE part_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE part_units ENABLE ROW LEVEL SECURITY;
ALTER TABLE ledger_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE attachments ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_exports ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_part_units ON part_units
USING (organization_id = current_setting('app.organization_id')::uuid)
WITH CHECK (organization_id = current_setting('app.organization_id')::uuid);

CREATE POLICY tenant_ledger_events ON ledger_events
USING (organization_id = current_setting('app.organization_id')::uuid)
WITH CHECK (organization_id = current_setting('app.organization_id')::uuid);
```

Equivalent policies apply to all organization-owned tables. The application database role must not own those tables and must not have `BYPASSRLS`. Integration workers use a short-lived, organization-scoped credential and set the same guarded database context. Automated tests must attempt cross-organization reads, writes, export requests, attachment links, and foreign-key references; every attempt must fail.

## Migration from the current SQLite proof loop

Run the production workspace beside the current single-tenant SQLite service rather than modifying a live ledger in place. Map the current `parts` record to `part_revisions` plus `part_units` as follows: `part_number` and `revision` become a revision; the historical `part_id` becomes the initial unit identifier; every existing event retains its original timestamp, reference, payload, source data, and event ID in a migration mapping table.

The migration must create one designated organization, mark imported actors as legacy provenance until they are resolved to a real membership or service principal, preserve the original event order, calculate a manifest hash before and after migration, and make the SQLite database read-only after cutover. No migration may alter a historical event to make it fit the new model; a mismatch is a documented gap and a human decision.

## Delivery acceptance criteria

The design is ready to implement when the backend can prove all of the following: a user in Organization A cannot discover or reference data in Organization B; an organization administrator cannot approve a part merely by being an administrator; an Inspector can log an inspection result but cannot release or accept a part; an integration token cannot write a human-only event; an event can be corrected but never updated or removed; and every export has a retrievable manifest, a requesting membership, and an integrity digest.
