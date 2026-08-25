"""
Earthward Rescue Task Force — incident log service.

This is the ONLY thing allowed to write to the incident store.
Every rescue agent talks to this module's public entry points —
log_action(), get_incident(), open_incident() — never to the
database directly.

Mirrors services/traceability/service.py exactly:
  - append-only event log; corrections reference, never overwrite
  - action_type sequencing enforced in code, not just in prompts
  - human-only action types rejected outright if source is an agent
  - current_status derived from action history, never stored
  - gaps reported, never inferred or backfilled
  - zero external dependencies beyond the Python standard library

Enforces in code the cross-cutting rules from docs/build-order.md:
  1. No agent self-certifies its own output.
  2. No agent hides a failure to look complete.
  3. No agent invents a standard or authorization.
  4. Every escalation names who it goes to.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Optional

from models import (
    ActionSource,
    ActionType,
    IncidentPriority,
    IncidentType,
    MissingReferenceError,
    RescueError,
    UnauthorizedSourceError,
    UnknownIncidentError,
    InvalidSequenceError,
    HazardBlockError,
    HUMAN_ONLY_ACTION_TYPES,
    now_iso,
)


# Configurable so a deployed container can point the append-only store at a
# mounted volume instead of the (ephemeral, container-local) default path.
DB_PATH = Path(os.environ.get("RESCUE_DB_PATH") or (Path(__file__).parent / "earthward_rescue.db"))


# ---------------------------------------------------------------------------
# Sequencing rules — hard preconditions enforced in code
# Mirrors traceability._check_sequence() — deliberately narrow and auditable.
# ---------------------------------------------------------------------------

# Actions that must exist before a given action_type is allowed.
# Each entry: action_type -> set of prerequisite action_types (at least one must exist).
_SEQUENCE_PRECONDITIONS: dict[ActionType, set[ActionType]] = {
    ActionType.OPERATIONAL_PLAN_APPROVED: {ActionType.OPERATIONAL_PLAN_DRAFTED},
    ActionType.TEAM_DEPLOYED:             {ActionType.OPERATIONAL_PLAN_APPROVED},
    ActionType.EXTRACTION_STARTED:        {ActionType.VICTIM_LOCATED},
    ActionType.EXTRACTION_COMPLETE:       {ActionType.EXTRACTION_STARTED},
    ActionType.VICTIM_STABILIZED:         {ActionType.VICTIM_ASSESSED},
    ActionType.VICTIM_TRANSFERRED:        {ActionType.VICTIM_STABILIZED},
    ActionType.OBJECTIVE_VERIFIED:        {ActionType.TEAM_DEPLOYED},
    ActionType.HAZARD_MITIGATED:          {ActionType.HAZARD_OPENED},
    ActionType.HAZARD_CLEARED:            {ActionType.HAZARD_OPENED},
    ActionType.INCIDENT_CLOSED:           {ActionType.OBJECTIVE_VERIFIED},
    ActionType.AFTER_ACTION_FILED:        {ActionType.INCIDENT_CLOSED},
}

# Actions blocked when an open critical/high hazard exists.
_HAZARD_BLOCKED_ACTIONS: frozenset[ActionType] = frozenset({
    ActionType.TEAM_DEPLOYED,
    ActionType.EXTRACTION_STARTED,
    ActionType.VICTIM_TRANSFERRED,
    ActionType.INCIDENT_CLOSED,
})


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(reset: bool = False) -> None:
    """
    Create the schema. reset=True drops and recreates — dev/demo only.
    Never call reset=True against a real incident record.
    """
    if reset and DB_PATH.exists():
        DB_PATH.unlink()

    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS incidents (
            incident_id   TEXT PRIMARY KEY,
            incident_type TEXT NOT NULL,
            priority      TEXT NOT NULL,
            location      TEXT NOT NULL,
            description   TEXT NOT NULL,
            reported_at   TEXT NOT NULL,
            source_type   TEXT NOT NULL,
            source_id     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS incident_actions (
            action_id           TEXT PRIMARY KEY,
            incident_id         TEXT NOT NULL,
            timestamp           TEXT NOT NULL,
            action_type         TEXT NOT NULL,
            source_type         TEXT NOT NULL,
            source_id           TEXT NOT NULL,
            reference           TEXT NOT NULL,
            corrects_action_id  TEXT,
            data_json           TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
        );

        CREATE TABLE IF NOT EXISTS hazards (
            hazard_id     TEXT PRIMARY KEY,
            incident_id   TEXT NOT NULL,
            description   TEXT NOT NULL,
            severity      TEXT NOT NULL,
            opened_at     TEXT NOT NULL,
            source_type   TEXT NOT NULL,
            source_id     TEXT NOT NULL,
            mitigated_at  TEXT,
            cleared_at    TEXT,
            cleared_by_type TEXT,
            cleared_by_id   TEXT,
            notes         TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
        );

        CREATE TABLE IF NOT EXISTS escalations (
            escalation_id  TEXT PRIMARY KEY,
            incident_id    TEXT NOT NULL,
            timestamp      TEXT NOT NULL,
            raised_by      TEXT NOT NULL,
            escalate_to    TEXT NOT NULL,
            reason         TEXT NOT NULL,
            action_required TEXT NOT NULL,
            resolved       INTEGER NOT NULL DEFAULT 0,
            resolved_at    TEXT,
            resolved_by    TEXT,
            FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
        );

        CREATE TABLE IF NOT EXISTS victims (
            victim_id            TEXT PRIMARY KEY,
            incident_id          TEXT NOT NULL,
            description          TEXT NOT NULL,
            location_description TEXT NOT NULL,
            triage_category      TEXT NOT NULL,
            located_at           TEXT,
            extracted_at         TEXT,
            transferred_at       TEXT,
            FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
        );

        CREATE TABLE IF NOT EXISTS operational_plans (
            plan_id       TEXT PRIMARY KEY,
            incident_id   TEXT NOT NULL,
            drafted_by    TEXT NOT NULL,
            objectives_json       TEXT NOT NULL DEFAULT '[]',
            team_assignments_json TEXT NOT NULL DEFAULT '{}',
            resource_assignments_json TEXT NOT NULL DEFAULT '{}',
            assumptions_json      TEXT NOT NULL DEFAULT '[]',
            open_questions_json   TEXT NOT NULL DEFAULT '[]',
            status        TEXT NOT NULL DEFAULT 'draft',
            approved_by   TEXT,
            approved_at   TEXT,
            FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
        );

        CREATE INDEX IF NOT EXISTS idx_actions_incident ON incident_actions(incident_id);
        CREATE INDEX IF NOT EXISTS idx_hazards_incident ON hazards(incident_id);
        CREATE INDEX IF NOT EXISTS idx_escalations_incident ON escalations(incident_id);
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _incident_exists(conn: sqlite3.Connection, incident_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM incidents WHERE incident_id = ?", (incident_id,)
    ).fetchone()
    return row is not None


def _action_types_logged(conn: sqlite3.Connection, incident_id: str) -> list[ActionType]:
    rows = conn.execute(
        "SELECT action_type FROM incident_actions WHERE incident_id = ? ORDER BY timestamp",
        (incident_id,),
    ).fetchall()
    return [ActionType(r["action_type"]) for r in rows]


def _open_critical_hazard_count(conn: sqlite3.Connection, incident_id: str) -> int:
    rows = conn.execute(
        """SELECT COUNT(*) as cnt FROM hazards
           WHERE incident_id = ? AND severity IN ('critical','high') AND cleared_at IS NULL""",
        (incident_id,),
    ).fetchone()
    return rows["cnt"] if rows else 0


def _check_sequence(
    action_type: ActionType,
    logged: list[ActionType],
    open_critical_hazards: int,
) -> None:
    """
    Hard preconditions — narrow and auditable. Enforces named dependencies
    from the incident lifecycle, same pattern as traceability._check_sequence().
    """
    preconditions = _SEQUENCE_PRECONDITIONS.get(action_type)
    if preconditions:
        logged_set = set(logged)
        if not preconditions.intersection(logged_set):
            missing = ", ".join(a.value for a in preconditions)
            raise InvalidSequenceError(
                f"Cannot log '{action_type.value}' — prerequisite action(s) "
                f"not yet logged: {missing}."
            )

    if action_type in _HAZARD_BLOCKED_ACTIONS and open_critical_hazards > 0:
        raise HazardBlockError(
            f"Cannot log '{action_type.value}' — {open_critical_hazards} open "
            f"critical/high hazard(s) must be cleared by a human first."
        )


# ---------------------------------------------------------------------------
# Public write API
# ---------------------------------------------------------------------------

def open_incident(
    incident_type: IncidentType,
    priority: IncidentPriority,
    location: str,
    description: str,
    source: ActionSource,
    incident_id: Optional[str] = None,
) -> str:
    """
    Register a new incident. Returns the incident_id.
    Automatically logs an INCIDENT_OPENED action.
    """
    incident_id = incident_id or str(uuid.uuid4())
    ts = now_iso()
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO incidents
               (incident_id, incident_type, priority, location, description,
                reported_at, source_type, source_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                incident_id,
                incident_type.value,
                priority.value,
                location,
                description,
                ts,
                source.type,
                source.id,
            ),
        )
        # Auto-log the opening action — no sequence check needed for INCIDENT_OPENED.
        action_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO incident_actions
               (action_id, incident_id, timestamp, action_type,
                source_type, source_id, reference, data_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                action_id,
                incident_id,
                ts,
                ActionType.INCIDENT_OPENED.value,
                source.type,
                source.id,
                f"incident-open-{incident_id}",
                json.dumps({"priority": priority.value, "type": incident_type.value}),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return incident_id


def _log_action_conn(
    conn: sqlite3.Connection,
    incident_id: str,
    action_type: ActionType,
    source: ActionSource,
    reference: str,
    data: Optional[dict[str, Any]] = None,
    corrects_action_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Internal: write an action using an already-open connection.
    Used by open_hazard, clear_hazard, add_victim, draft_plan, approve_plan
    so they can share a single transaction without hitting a lock.
    All rules are still enforced — nothing is bypassed.
    """
    if not reference:
        raise MissingReferenceError(
            "reference is required — every action must point to supporting "
            "data (radio log ID, report number, order reference). "
            "Free text alone is not a valid reference."
        )

    if action_type in HUMAN_ONLY_ACTION_TYPES and not source.is_human():
        raise UnauthorizedSourceError(
            f"'{action_type.value}' requires a human source. "
            f"Got source.type={source.type!r} (id={source.id!r}). "
            f"Agents may recommend this action but cannot log it themselves."
        )

    if action_type == ActionType.CORRECTION and not corrects_action_id:
        raise RescueError("CORRECTION actions must set corrects_action_id.")

    if corrects_action_id:
        original = conn.execute(
            "SELECT 1 FROM incident_actions WHERE action_id = ? AND incident_id = ?",
            (corrects_action_id, incident_id),
        ).fetchone()
        if not original:
            raise RescueError(
                f"corrects_action_id {corrects_action_id!r} does not exist "
                f"on this incident — cannot correct an action that was never logged."
            )

    logged = _action_types_logged(conn, incident_id)
    open_hazards = _open_critical_hazard_count(conn, incident_id)
    _check_sequence(action_type, logged, open_hazards)

    action_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO incident_actions
           (action_id, incident_id, timestamp, action_type,
            source_type, source_id, reference, corrects_action_id, data_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            action_id,
            incident_id,
            now_iso(),
            action_type.value,
            source.type,
            source.id,
            reference,
            corrects_action_id,
            json.dumps(data or {}),
        ),
    )
    return {
        "action_id": action_id,
        "incident_id": incident_id,
        "action_type": action_type.value,
    }


def log_action(
    incident_id: str,
    action_type: ActionType,
    source: ActionSource,
    reference: str,
    data: Optional[dict[str, Any]] = None,
    corrects_action_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    The ONLY public way to write to an incident's action history.
    Append-only — never edits or deletes a prior action.

    Raises RescueError (or subclass) on any rule violation.
    The caller is responsible for surfacing that rejection —
    this function never downgrades a rejection into a silent no-op.
    """
    conn = _connect()
    try:
        if not _incident_exists(conn, incident_id):
            raise UnknownIncidentError(f"No such incident_id: {incident_id!r}")
        result = _log_action_conn(
            conn, incident_id, action_type, source, reference, data, corrects_action_id
        )
        conn.commit()
        return result
    finally:
        conn.close()


def open_hazard(
    incident_id: str,
    description: str,
    severity: str,
    source: ActionSource,
    notes: str = "",
) -> str:
    """Register a new hazard against an incident. Returns hazard_id."""
    if severity not in ("critical", "high", "moderate", "low"):
        raise RescueError(f"Invalid severity: {severity!r}. Must be critical|high|moderate|low.")
    conn = _connect()
    try:
        if not _incident_exists(conn, incident_id):
            raise UnknownIncidentError(f"No such incident_id: {incident_id!r}")
        hazard_id = str(uuid.uuid4())
        ts = now_iso()
        conn.execute(
            """INSERT INTO hazards
               (hazard_id, incident_id, description, severity, opened_at,
                source_type, source_id, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (hazard_id, incident_id, description, severity, ts,
             source.type, source.id, notes),
        )
        # Also log the action so it appears in the incident timeline.
        _log_action_conn(
            conn,
            incident_id=incident_id,
            action_type=ActionType.HAZARD_OPENED,
            source=source,
            reference=f"hazard-{hazard_id}",
            data={"hazard_id": hazard_id, "severity": severity, "description": description},
        )
        conn.commit()
        return hazard_id
    finally:
        conn.close()


def clear_hazard(
    incident_id: str,
    hazard_id: str,
    source: ActionSource,
    notes: str = "",
) -> None:
    """
    Clear a hazard — human-only. Mirrors ncr_closed in the traceability service.
    """
    if not source.is_human():
        raise UnauthorizedSourceError(
            "Clearing a hazard requires a human source. "
            f"Got source.type={source.type!r} (id={source.id!r})."
        )
    conn = _connect()
    try:
        if not _incident_exists(conn, incident_id):
            raise UnknownIncidentError(f"No such incident_id: {incident_id!r}")
        existing = conn.execute(
            "SELECT * FROM hazards WHERE hazard_id = ? AND incident_id = ?",
            (hazard_id, incident_id),
        ).fetchone()
        if not existing:
            raise RescueError(f"No such hazard_id: {hazard_id!r} on incident {incident_id!r}")
        if existing["cleared_at"] is not None:
            raise RescueError(f"Hazard {hazard_id!r} is already cleared.")
        ts = now_iso()
        conn.execute(
            """UPDATE hazards SET cleared_at = ?, cleared_by_type = ?,
               cleared_by_id = ?, notes = ? WHERE hazard_id = ?""",
            (ts, source.type, source.id, notes, hazard_id),
        )
        _log_action_conn(
            conn,
            incident_id=incident_id,
            action_type=ActionType.HAZARD_CLEARED,
            source=source,
            reference=f"hazard-{hazard_id}",
            data={"hazard_id": hazard_id, "notes": notes},
        )
        conn.commit()
    finally:
        conn.close()


def add_victim(
    incident_id: str,
    description: str,
    location_description: str,
    triage_category: str,
    source: ActionSource,
) -> str:
    """Register a victim against an incident. Returns victim_id."""
    valid_triage = {"immediate", "delayed", "minimal", "expectant"}
    if triage_category not in valid_triage:
        raise RescueError(f"Invalid triage_category: {triage_category!r}. Must be one of {valid_triage}.")
    conn = _connect()
    try:
        if not _incident_exists(conn, incident_id):
            raise UnknownIncidentError(f"No such incident_id: {incident_id!r}")
        victim_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO victims
               (victim_id, incident_id, description, location_description, triage_category)
               VALUES (?, ?, ?, ?, ?)""",
            (victim_id, incident_id, description, location_description, triage_category),
        )
        _log_action_conn(
            conn,
            incident_id=incident_id,
            action_type=ActionType.VICTIM_LOCATED,
            source=source,
            reference=f"victim-{victim_id}",
            data={"victim_id": victim_id, "triage_category": triage_category},
        )
        conn.commit()
        return victim_id
    finally:
        conn.close()


def raise_escalation(
    incident_id: str,
    raised_by: str,
    escalate_to: str,
    reason: str,
    action_required: str,
) -> str:
    """
    Log an escalation. escalate_to must name a specific person or role —
    never just 'a human'. Returns escalation_id.
    """
    if not escalate_to or escalate_to.strip().lower() in ("a human", "human", "someone"):
        raise RescueError(
            "escalate_to must name a specific person or role "
            "(e.g. 'Incident Commander', 'Safety Officer IC-7'). "
            "Vague targets are rejected."
        )
    conn = _connect()
    try:
        if not _incident_exists(conn, incident_id):
            raise UnknownIncidentError(f"No such incident_id: {incident_id!r}")
        escalation_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO escalations
               (escalation_id, incident_id, timestamp, raised_by,
                escalate_to, reason, action_required)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                escalation_id,
                incident_id,
                now_iso(),
                raised_by,
                escalate_to,
                reason,
                action_required,
            ),
        )
        conn.commit()
        return escalation_id
    finally:
        conn.close()


def resolve_escalation(
    escalation_id: str,
    resolved_by: str,
) -> None:
    """Mark an escalation resolved. resolved_by must be a named human."""
    conn = _connect()
    try:
        existing = conn.execute(
            "SELECT * FROM escalations WHERE escalation_id = ?",
            (escalation_id,),
        ).fetchone()
        if not existing:
            raise RescueError(f"No such escalation_id: {escalation_id!r}")
        if existing["resolved"]:
            raise RescueError(f"Escalation {escalation_id!r} is already resolved.")
        conn.execute(
            "UPDATE escalations SET resolved = 1, resolved_at = ?, resolved_by = ? WHERE escalation_id = ?",
            (now_iso(), resolved_by, escalation_id),
        )
        conn.commit()
    finally:
        conn.close()


def draft_plan(
    incident_id: str,
    drafted_by: str,
    objectives: list[str],
    team_assignments: dict[str, str],
    resource_assignments: dict[str, str],
    assumptions: list[str],
    open_questions: list[str],
) -> str:
    """
    Draft an operational plan — agent-submittable, always status='draft'.
    Approval is human-only, via approve_plan(). Returns plan_id.
    """
    conn = _connect()
    try:
        if not _incident_exists(conn, incident_id):
            raise UnknownIncidentError(f"No such incident_id: {incident_id!r}")
        plan_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO operational_plans
               (plan_id, incident_id, drafted_by, objectives_json,
                team_assignments_json, resource_assignments_json,
                assumptions_json, open_questions_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                plan_id,
                incident_id,
                drafted_by,
                json.dumps(objectives),
                json.dumps(team_assignments),
                json.dumps(resource_assignments),
                json.dumps(assumptions),
                json.dumps(open_questions),
            ),
        )
        _log_action_conn(
            conn,
            incident_id=incident_id,
            action_type=ActionType.OPERATIONAL_PLAN_DRAFTED,
            source=ActionSource(type="agent", id=drafted_by),
            reference=f"plan-{plan_id}",
            data={"plan_id": plan_id, "objectives": objectives},
        )
        conn.commit()
        return plan_id
    finally:
        conn.close()


def approve_plan(
    plan_id: str,
    incident_id: str,
    approved_by: ActionSource,
) -> None:
    """
    Approve an operational plan — human-only.
    Mirrors acceptance_decision in the traceability service.
    """
    if not approved_by.is_human():
        raise UnauthorizedSourceError(
            "Plan approval requires a human source. "
            f"Got source.type={approved_by.type!r} (id={approved_by.id!r}). "
            "Agents may draft plans but cannot approve them."
        )
    conn = _connect()
    try:
        plan = conn.execute(
            "SELECT * FROM operational_plans WHERE plan_id = ? AND incident_id = ?",
            (plan_id, incident_id),
        ).fetchone()
        if not plan:
            raise RescueError(f"No such plan_id: {plan_id!r} on incident {incident_id!r}")
        if plan["status"] == "approved":
            raise RescueError(f"Plan {plan_id!r} is already approved.")
        ts = now_iso()
        conn.execute(
            "UPDATE operational_plans SET status = 'approved', approved_by = ?, approved_at = ? WHERE plan_id = ?",
            (approved_by.id, ts, plan_id),
        )
        _log_action_conn(
            conn,
            incident_id=incident_id,
            action_type=ActionType.OPERATIONAL_PLAN_APPROVED,
            source=approved_by,
            reference=f"plan-{plan_id}",
            data={"plan_id": plan_id, "approved_by": approved_by.id},
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------

def get_incident(incident_id: str) -> dict[str, Any]:
    """
    Read the full, faithful record for an incident plus derived status
    and open escalations. Read-only, never mutates.
    Mirrors traceability.get_record() exactly.
    """
    conn = _connect()
    try:
        inc = conn.execute(
            "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
        ).fetchone()
        if not inc:
            raise UnknownIncidentError(f"No such incident_id: {incident_id!r}")

        actions = [
            {
                "action_id": r["action_id"],
                "timestamp": r["timestamp"],
                "action_type": r["action_type"],
                "source": {"type": r["source_type"], "id": r["source_id"]},
                "reference": r["reference"],
                "corrects_action_id": r["corrects_action_id"],
                "data": json.loads(r["data_json"]),
            }
            for r in conn.execute(
                "SELECT * FROM incident_actions WHERE incident_id = ? ORDER BY timestamp",
                (incident_id,),
            ).fetchall()
        ]

        hazards = [
            {
                "hazard_id": r["hazard_id"],
                "description": r["description"],
                "severity": r["severity"],
                "opened_at": r["opened_at"],
                "cleared_at": r["cleared_at"],
                "is_open": r["cleared_at"] is None,
            }
            for r in conn.execute(
                "SELECT * FROM hazards WHERE incident_id = ?", (incident_id,)
            ).fetchall()
        ]

        escalations = [
            {
                "escalation_id": r["escalation_id"],
                "timestamp": r["timestamp"],
                "raised_by": r["raised_by"],
                "escalate_to": r["escalate_to"],
                "reason": r["reason"],
                "action_required": r["action_required"],
                "resolved": bool(r["resolved"]),
            }
            for r in conn.execute(
                "SELECT * FROM escalations WHERE incident_id = ?", (incident_id,)
            ).fetchall()
        ]

        victims = [
            {
                "victim_id": r["victim_id"],
                "description": r["description"],
                "location_description": r["location_description"],
                "triage_category": r["triage_category"],
                "located_at": r["located_at"],
                "extracted_at": r["extracted_at"],
                "transferred_at": r["transferred_at"],
            }
            for r in conn.execute(
                "SELECT * FROM victims WHERE incident_id = ?", (incident_id,)
            ).fetchall()
        ]

        plans = [
            {
                "plan_id": r["plan_id"],
                "drafted_by": r["drafted_by"],
                "status": r["status"],
                "objectives": json.loads(r["objectives_json"]),
                "team_assignments": json.loads(r["team_assignments_json"]),
                "resource_assignments": json.loads(r["resource_assignments_json"]),
                "assumptions": json.loads(r["assumptions_json"]),
                "open_questions": json.loads(r["open_questions_json"]),
                "approved_by": r["approved_by"],
                "approved_at": r["approved_at"],
            }
            for r in conn.execute(
                "SELECT * FROM operational_plans WHERE incident_id = ?", (incident_id,)
            ).fetchall()
        ]

        # Derive status from action history — never stored directly.
        open_critical = sum(1 for h in hazards if h["is_open"] and h["severity"] in ("critical", "high"))
        current_status = _derive_status(actions, open_critical)

        open_escalation_count = sum(1 for e in escalations if not e["resolved"])

        return {
            "incident_id": inc["incident_id"],
            "incident_type": inc["incident_type"],
            "priority": inc["priority"],
            "location": inc["location"],
            "description": inc["description"],
            "reported_at": inc["reported_at"],
            "current_status": current_status,
            "open_escalations": open_escalation_count,
            "open_hazards": open_critical,
            "actions": actions,
            "hazards": hazards,
            "escalations": escalations,
            "victims": victims,
            "operational_plans": plans,
        }
    finally:
        conn.close()


def _derive_status(actions: list[dict], open_critical_hazards: int) -> str:
    """
    current_status is ALWAYS computed from action history, never stored.
    Mirrors traceability._derive_status() exactly.
    """
    if not actions:
        return "reported"

    types_seen = {a["action_type"] for a in actions}

    if ActionType.INCIDENT_CLOSED.value in types_seen:
        return "closed"
    if ActionType.VICTIM_TRANSFERRED.value in types_seen:
        return "transferring"
    if ActionType.EXTRACTION_STARTED.value in types_seen:
        return "extracting"
    if open_critical_hazards > 0:
        return "hazard_blocked"
    if ActionType.TEAM_DEPLOYED.value in types_seen:
        return "operations"
    if ActionType.OPERATIONAL_PLAN_APPROVED.value in types_seen:
        return "planning"
    if ActionType.SITUATION_REPORT.value in types_seen:
        return "assessing"

    return "reported"


def list_open_incidents() -> list[dict[str, Any]]:
    """Return a summary of all incidents that are not closed."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM incidents ORDER BY reported_at DESC"
        ).fetchall()
        results = []
        for r in rows:
            # Derive status cheaply without loading all events.
            actions = conn.execute(
                "SELECT action_type FROM incident_actions WHERE incident_id = ?",
                (r["incident_id"],),
            ).fetchall()
            open_critical = conn.execute(
                """SELECT COUNT(*) as cnt FROM hazards
                   WHERE incident_id = ? AND severity IN ('critical','high')
                   AND cleared_at IS NULL""",
                (r["incident_id"],),
            ).fetchone()["cnt"]

            action_types = [a["action_type"] for a in actions]
            status = _derive_status(
                [{"action_type": t} for t in action_types],
                open_critical,
            )
            if status == "closed":
                continue
            results.append({
                "incident_id": r["incident_id"],
                "incident_type": r["incident_type"],
                "priority": r["priority"],
                "location": r["location"],
                "current_status": status,
                "reported_at": r["reported_at"],
            })
        return results
    finally:
        conn.close()
