"""
Earthward Traceability Service — core logic.

This module is the ONLY thing allowed to write to the part_records store.
Every house agent (Manufacturing Engineer, CMM, Quality, etc.) talks to
this module's two public entry points — append_event() and get_record()
— never to the database directly.

Deliberately zero external dependencies. This is the spine everything
else depends on; it should not depend on anything itself beyond the
Python standard library.

Enforces in code (not just in the prompt) the rules from
schema/part-record.schema.json and docs/build-order.md:
  - events are append-only; corrections reference, never overwrite
  - event_type sequencing must be valid for the part's current state
  - acceptance_decision, ncr_closed, and ncr_waived can only be written
    with a human source — an agent attempting one of these is rejected,
    not silently downgraded
  - current_status is always derived from event history, never stored
    as an independent, directly-settable field
  - a gap in the required sequence is reported, never inferred/backfilled
"""

from __future__ import annotations

import os
import sqlite3
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# Configurable so a deployed container can point the append-only store at a
# mounted volume instead of the (ephemeral, container-local) default path.
DB_PATH = Path(os.environ.get("TRACEABILITY_DB_PATH") or (Path(__file__).parent / "earthward_traceability.db"))

VALID_EVENT_TYPES = {
    "material_receipt",
    "material_verification",
    "process_step_start",
    "process_step_complete",
    "process_deviation",
    "inspection_program_run",
    "inspection_result",
    "ncr_opened",
    "ncr_closed",
    "ncr_waived",
    "acceptance_decision",
    "correction",
    "shipment",
}

# Event types that carry irreversible/authority-bearing weight.
# The schema doc says these require a human sign-off. We enforce that
# here, in code, rather than trusting every calling agent's prompt.
HUMAN_ONLY_EVENT_TYPES = {
    "acceptance_decision",
    "ncr_closed",
    "ncr_waived",
}

# current_status values, and the event_type that can move a part INTO
# that status. This is the sequencing rulebook — e.g. you cannot log
# "final acceptance" before "inspection_complete" exists in the chain.
STATUS_FLOW = {
    "material_received": {"material_receipt"},
    "in_process": {"process_step_start", "process_step_complete", "material_verification"},
    "inspection_pending": {"inspection_program_run"},
    "inspection_complete": {"inspection_result"},
    "ncr_open": {"ncr_opened"},
    "acceptance_blocked": {"ncr_opened"},
    "accepted": {"acceptance_decision"},
    "shipped": {"shipment"},
    "rejected": {"acceptance_decision"},
}


class TraceabilityError(Exception):
    """Base class for rejected writes. Every rejection is explicit —
    nothing is silently dropped or auto-corrected."""


class UnknownPartError(TraceabilityError):
    pass


class InvalidSequenceError(TraceabilityError):
    pass


class UnauthorizedSourceError(TraceabilityError):
    pass


@dataclass
class Source:
    type: str  # "agent" | "human"
    id: str

    def __post_init__(self):
        if self.type not in ("agent", "human"):
            raise ValueError(f"source.type must be 'agent' or 'human', got {self.type!r}")


@dataclass
class GapReport:
    part_id: str
    missing: list[str] = field(default_factory=list)

    @property
    def has_gap(self) -> bool:
        return len(self.missing) > 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(reset: bool = False) -> None:
    """Create the schema. reset=True drops and recreates (dev/demo only —
    never call reset=True against a real production record)."""
    if reset and DB_PATH.exists():
        DB_PATH.unlink()

    conn = _connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS parts (
            part_id      TEXT PRIMARY KEY,
            part_number  TEXT NOT NULL,
            revision     TEXT NOT NULL,
            created_at   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events (
            event_id          TEXT PRIMARY KEY,
            part_id           TEXT NOT NULL,
            timestamp         TEXT NOT NULL,
            event_type        TEXT NOT NULL,
            source_type       TEXT NOT NULL,
            source_id         TEXT NOT NULL,
            reference         TEXT NOT NULL,
            corrects_event_id TEXT,
            data_json         TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (part_id) REFERENCES parts(part_id)
        );

        CREATE INDEX IF NOT EXISTS idx_events_part_id ON events(part_id);
        """
    )
    conn.commit()
    conn.close()


def create_part(part_number: str, revision: str, part_id: Optional[str] = None) -> str:
    """Register a new physical part instance. Returns the part_id."""
    part_id = part_id or str(uuid.uuid4())
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO parts (part_id, part_number, revision, created_at) VALUES (?, ?, ?, ?)",
            (part_id, part_number, revision, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    return part_id


def _part_exists(conn: sqlite3.Connection, part_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM parts WHERE part_id = ?", (part_id,)).fetchone()
    return row is not None


def _event_types_logged(conn: sqlite3.Connection, part_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT event_type FROM events WHERE part_id = ? ORDER BY timestamp", (part_id,)
    ).fetchall()
    return [r["event_type"] for r in rows]


def append_event(
    part_id: str,
    event_type: str,
    source: Source,
    reference: str,
    data: Optional[dict[str, Any]] = None,
    corrects_event_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    The ONLY way to write to a part's history. Append-only — never edits
    or deletes a prior event.

    Raises TraceabilityError (or a subclass) on any rule violation. The
    caller (an agent or a human-facing API layer) is responsible for
    surfacing that rejection — this function never downgrades a rejection
    into a silent no-op.
    """
    if event_type not in VALID_EVENT_TYPES:
        raise TraceabilityError(f"Unknown event_type: {event_type!r}")

    if not reference:
        raise TraceabilityError(
            "reference is required — every event must point to supporting "
            "data (cert number, inspection report ID, NCR ID, sign-off record "
            "ID). Free text alone is not a valid reference."
        )

    # Rule: certain event types are authority-bearing and can only be
    # written with a human source. An agent attempting one of these is
    # rejected outright — this is enforced here, not left to the prompt.
    if event_type in HUMAN_ONLY_EVENT_TYPES and source.type != "human":
        raise UnauthorizedSourceError(
            f"'{event_type}' requires a human source. "
            f"Got source.type={source.type!r} (id={source.id!r}). "
            f"Agents may recommend this action but cannot log it themselves."
        )

    conn = _connect()
    try:
        if not _part_exists(conn, part_id):
            raise UnknownPartError(f"No such part_id: {part_id!r}")

        if event_type == "correction" and not corrects_event_id:
            raise TraceabilityError("correction events must set corrects_event_id")

        if corrects_event_id:
            original = conn.execute(
                "SELECT 1 FROM events WHERE event_id = ? AND part_id = ?",
                (corrects_event_id, part_id),
            ).fetchone()
            if not original:
                raise TraceabilityError(
                    f"corrects_event_id {corrects_event_id!r} does not exist "
                    f"on this part — cannot correct an event that was never logged."
                )

        # Sequencing check: does this part's current history make this
        # event_type valid right now? We keep this deliberately permissive
        # for non-terminal event types (process steps, verifications can
        # repeat) and strict only where the schema/build-order docs call
        # out a hard precondition.
        logged = _event_types_logged(conn, part_id)
        _check_sequence(event_type, logged)

        event_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO events
               (event_id, part_id, timestamp, event_type, source_type,
                source_id, reference, corrects_event_id, data_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                part_id,
                _now_iso(),
                event_type,
                source.type,
                source.id,
                reference,
                corrects_event_id,
                json.dumps(data or {}),
            ),
        )
        conn.commit()
        return {"event_id": event_id, "part_id": part_id, "event_type": event_type}
    finally:
        conn.close()


def _check_sequence(event_type: str, logged: list[str]) -> None:
    """Hard preconditions called out explicitly in the schema docs.
    Deliberately narrow — we enforce the cases that were named
    ("cannot log final acceptance before inspection_complete exists"),
    not a full state machine, so this stays auditable and doesn't
    silently reject things nobody asked it to gate."""

    if event_type == "acceptance_decision":
        if "inspection_result" not in logged:
            raise InvalidSequenceError(
                "Cannot log acceptance_decision before an inspection_result "
                "event exists on this part."
            )

    if event_type == "inspection_result":
        if "inspection_program_run" not in logged:
            raise InvalidSequenceError(
                "Cannot log inspection_result before inspection_program_run "
                "exists on this part."
            )

    if event_type in ("ncr_closed", "ncr_waived"):
        if "ncr_opened" not in logged:
            raise InvalidSequenceError(
                f"Cannot log {event_type} — no ncr_opened event exists on this part."
            )

    if event_type == "shipment":
        if "acceptance_decision" not in logged:
            raise InvalidSequenceError(
                "Cannot log shipment before an acceptance_decision exists on this part."
            )


def _derive_status(events: list[dict[str, Any]]) -> str:
    """current_status is ALWAYS computed from event history, never stored
    or set directly — this makes it recomputable/auditable at any time,
    per the schema design notes."""
    if not events:
        return "material_received"  # not yet even that, but a sane default for an empty record

    types_seen = [e["event_type"] for e in events]
    open_ncrs = types_seen.count("ncr_opened") - types_seen.count("ncr_closed") - types_seen.count("ncr_waived")

    # Walk in reverse priority: later/terminal states win if their
    # precondition is satisfied.
    if "shipment" in types_seen:
        return "shipped"

    last_acceptance = [e for e in events if e["event_type"] == "acceptance_decision"]
    if last_acceptance:
        decision = last_acceptance[-1]["data"].get("decision")
        return "rejected" if decision == "reject" else "accepted"

    if open_ncrs > 0:
        return "acceptance_blocked" if "inspection_result" in types_seen else "ncr_open"

    if "inspection_result" in types_seen:
        return "inspection_complete"
    if "inspection_program_run" in types_seen:
        return "inspection_pending"
    if any(t in types_seen for t in ("process_step_start", "process_step_complete")):
        return "in_process"
    if "material_receipt" in types_seen:
        return "material_received"

    return "material_received"


def get_record(part_id: str) -> dict[str, Any]:
    """Read the full, faithful history for a part, plus derived status
    and a gap report. This is the other half of the two-function
    contract every agent uses — read-only, never mutates."""
    conn = _connect()
    try:
        part = conn.execute(
            "SELECT * FROM parts WHERE part_id = ?", (part_id,)
        ).fetchone()
        if not part:
            raise UnknownPartError(f"No such part_id: {part_id!r}")

        rows = conn.execute(
            "SELECT * FROM events WHERE part_id = ? ORDER BY timestamp", (part_id,)
        ).fetchall()

        events = [
            {
                "event_id": r["event_id"],
                "timestamp": r["timestamp"],
                "event_type": r["event_type"],
                "source": {"type": r["source_type"], "id": r["source_id"]},
                "reference": r["reference"],
                "corrects_event_id": r["corrects_event_id"],
                "data": json.loads(r["data_json"]),
            }
            for r in rows
        ]

        return {
            "part_id": part["part_id"],
            "part_number": part["part_number"],
            "revision": part["revision"],
            "current_status": _derive_status(events),
            "gap_report": check_gaps(part_id, events).__dict__,
            "events": events,
        }
    finally:
        conn.close()


def check_gaps(part_id: str, events: Optional[list[dict[str, Any]]] = None) -> GapReport:
    """Reports — never infers or backfills — a missing event where the
    build-order process requires one. A gap is a gap; it is surfaced,
    not smoothed over."""
    if events is None:
        record = get_record(part_id)
        events = record["events"]

    types_seen = {e["event_type"] for e in events}
    missing = []

    if "process_step_start" in types_seen and "inspection_program_run" not in types_seen:
        # part has started production but has no inspection program yet —
        # not necessarily wrong this early, so this is advisory, not fatal
        pass

    if "inspection_program_run" in types_seen and "inspection_result" not in types_seen:
        missing.append(
            "inspection_program_run logged but no inspection_result — run is incomplete"
        )

    if "acceptance_decision" in types_seen:
        open_ncrs = (
            sum(1 for e in events if e["event_type"] == "ncr_opened")
            - sum(1 for e in events if e["event_type"] in ("ncr_closed", "ncr_waived"))
        )
        if open_ncrs > 0:
            missing.append(
                "acceptance_decision logged but an NCR is still open/unresolved — "
                "this record needs human review"
            )

    return GapReport(part_id=part_id, missing=missing)
