"""
Earthward Rescue Task Force — narrated demo.

Walks one complete incident through the pipeline:

  INCIDENT: Partial structural collapse, apartment building, 2 confirmed
            trapped, gas leak reported. Urban SAR, life-threat priority.

  PHASE 1   Incident opened, log activated.
  PHASE 2   Safety Agent flags critical hazards — gas, structural instability.
            Escalates to Safety Officer. Pipeline continues (assessment
            doesn't require hazard clearance, only operations does).
  PHASE 3   Assessment Agent structures situational picture, reports gaps.
  PHASE 4   Resource Agent identifies minimum resource requirements, escalates
            to Logistics.
  PHASE 5   Planning Agent drafts operational plan — HALTS pipeline.
            Incident Commander approval required before operations.

  --- Human gate: plan approval ---

  PHASE 6   Incident Commander approves plan (human sign-off).
            Runner resumed. Operations Agent deploys teams.
  PHASE 7   Integration Agent checks coverage — one objective unassigned,
            escalates to Operations Section Chief.
  PHASE 8   Extraction complete logged by field team (human).
            Verification Agent confirms objectives met.
  PHASE 9   Command Agent rolls up final status.

  --- Intentional rejections (2) ---

  REJECT 1  Agent attempts to approve the plan itself. Rejected with
            UnauthorizedSourceError — approval requires human source.
  REJECT 2  Agent attempts to close the incident before objectives are
            verified. Rejected with InvalidSequenceError.

Run:
    cd services/rescue
    python demo.py
"""

import json
import sys
from pathlib import Path

# Make sure we can import our sibling modules when run directly.
sys.path.insert(0, str(Path(__file__).parent))

import incident_log as log
from models import ActionSource, ActionType, IncidentType, IncidentPriority
from models import UnauthorizedSourceError, InvalidSequenceError
from runner import TaskForceRunner


# ---------------------------------------------------------------------------
# Narration helpers
# ---------------------------------------------------------------------------

_WIDTH = 72

def _banner(title: str) -> None:
    print()
    print("=" * _WIDTH)
    print(f"  {title}")
    print("=" * _WIDTH)

def _section(title: str) -> None:
    print()
    print(f"--- {title} ---")

def _narrate(text: str) -> None:
    print(f"  {text}")

def _show(label: str, value) -> None:
    if isinstance(value, (dict, list)):
        print(f"  {label}:")
        lines = json.dumps(value, indent=4).splitlines()
        for line in lines:
            print(f"    {line}")
    else:
        print(f"  {label}: {value}")

def _ok(text: str) -> None:
    print(f"  [OK]     {text}")

def _rejected(text: str) -> None:
    print(f"  [REJECT] {text}")

def _waiting(text: str) -> None:
    print(f"  [GATE]   {text}")

def _escalation(text: str) -> None:
    print(f"  [ESC]    {text}")


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def run_demo():
    _banner("EARTHWARD RESCUE TASK FORCE — INCIDENT PIPELINE DEMO")
    _narrate("Incident: Partial structural collapse, 2 confirmed trapped, gas leak.")
    _narrate("Type: Urban SAR  |  Priority: LIFE THREAT")
    _narrate("All data is synthetic. No real emergency services are involved.")

    # Reset the DB for a clean demo run — never do this in production.
    log.init_db(reset=True)

    runner = TaskForceRunner()
    dispatcher = ActionSource(type="human", id="Dispatcher-IC1")
    ic = ActionSource(type="human", id="IncidentCommander-Reyes")

    # -----------------------------------------------------------------------
    _banner("PHASE 1–5: INTAKE — opening incident and running to plan approval gate")
    # -----------------------------------------------------------------------

    _section("Opening incident")
    result = runner.intake(
        incident_type=IncidentType.URBAN_SAR,
        priority=IncidentPriority.LIFE_THREAT,
        location="412 Alderton Ave — 4-story apartment, east wing collapse",
        description=(
            "Partial collapse of floors 2-3, east wing. "
            "2 confirmed trapped (voice contact), gas odor reported by first responders. "
            "Unknown additional victims."
        ),
        reported_by=dispatcher,
    )

    incident_id = result["incident_id"]
    _ok(f"Incident opened: {incident_id}")
    _show("Phases completed", result["phases_completed"])

    if result["escalations"]:
        _section("Escalations raised during intake")
        for esc in result["escalations"]:
            _escalation(
                f"Raised by: {esc.get('raised_by', '?')} "
                f"→ {esc.get('escalate_to', '?')}"
            )

    if result["awaiting_human"]:
        _waiting(result["awaiting_human"]["message"])

    if result["blocks"]:
        for block in result["blocks"]:
            _narrate(f"Pipeline halted at '{block['phase']}': {block['reason']}")

    # -----------------------------------------------------------------------
    _banner("ADDING FIELD DATA: victims and hazards logged by first responders")
    # -----------------------------------------------------------------------

    _section("Logging victims (first responder radio reports)")
    v1_id = log.add_victim(
        incident_id=incident_id,
        description="Adult female, voice contact, floor 2 east stairwell",
        location_description="Floor 2, east stairwell, debris blocking egress",
        triage_category="immediate",
        source=ActionSource(type="human", id="Team-Alpha-Lead"),
    )
    _ok(f"Victim 1 logged: {v1_id}")

    v2_id = log.add_victim(
        incident_id=incident_id,
        description="Adult male, voice contact, apartment 2C",
        location_description="Apartment 2C, floor slab shifted, ambulatory",
        triage_category="delayed",
        source=ActionSource(type="human", id="Team-Alpha-Lead"),
    )
    _ok(f"Victim 2 logged: {v2_id}")

    _section("Logging hazards (Safety Officer initial assessment)")
    safety_officer = ActionSource(type="human", id="SafetyOfficer-Nakamura")
    h1_id = log.open_hazard(
        incident_id=incident_id,
        description="Active gas leak — odor confirmed, utility not yet isolated",
        severity="critical",
        source=safety_officer,
        notes="Utility Control Officer en route. Entry prohibited until cleared.",
    )
    _ok(f"Hazard 1 logged (critical): {h1_id}")

    h2_id = log.open_hazard(
        incident_id=incident_id,
        description="Structural instability — floor 3 partially unsupported",
        severity="critical",
        source=safety_officer,
        notes="Structural Specialist assessment required before upper floor entry.",
    )
    _ok(f"Hazard 2 logged (critical): {h2_id}")

    # -----------------------------------------------------------------------
    _banner("INTENTIONAL REJECTION 1: Agent tries to approve the operational plan")
    # -----------------------------------------------------------------------

    _section("Agent attempts plan approval (should be rejected)")
    _narrate(
        "Planning Agent tries to approve its own draft plan. "
        "The rule: no agent self-certifies its own output. "
        "Plan approval requires a human source."
    )

    # Get the plan_id from the record.
    record = log.get_incident(incident_id)
    plans = record["operational_plans"]
    if plans:
        plan_id = plans[0]["plan_id"]
        try:
            log.approve_plan(
                plan_id=plan_id,
                incident_id=incident_id,
                approved_by=ActionSource(type="agent", id="planning-agent"),
            )
            print("  ERROR: This should have been rejected.")
        except UnauthorizedSourceError as e:
            _rejected(f"UnauthorizedSourceError: {e}")
    else:
        _narrate("(No plan drafted yet — run intake first.)")

    # -----------------------------------------------------------------------
    _banner("INTENTIONAL REJECTION 2: Agent tries to close incident before objectives verified")
    # -----------------------------------------------------------------------

    _section("Agent attempts incident closure (should be rejected)")
    _narrate(
        "Command Agent tries to log INCIDENT_CLOSED. "
        "Sequence rule: OBJECTIVE_VERIFIED must exist first."
    )
    try:
        log.log_action(
            incident_id=incident_id,
            action_type=ActionType.INCIDENT_CLOSED,
            source=ActionSource(type="human", id="IncidentCommander-Reyes"),
            reference="early-close-attempt",
        )
        print("  ERROR: This should have been rejected.")
    except InvalidSequenceError as e:
        _rejected(f"InvalidSequenceError: {e}")

    # -----------------------------------------------------------------------
    _banner("HUMAN GATE: Incident Commander clears hazards and approves plan")
    # -----------------------------------------------------------------------

    _section("Safety Officer clears gas hazard (utility isolated)")
    log.clear_hazard(
        incident_id=incident_id,
        hazard_id=h1_id,
        source=safety_officer,
        notes="Gas utility isolated confirmed by Utility Control Officer. Entry approved ground floor.",
    )
    _ok("Gas hazard cleared by Safety Officer.")

    _section("Safety Officer clears structural hazard (specialist on site)")
    log.clear_hazard(
        incident_id=incident_id,
        hazard_id=h2_id,
        source=safety_officer,
        notes="Structural Specialist confirms floors 2 east corridor safe for entry with shoring. Floor 3 prohibited.",
    )
    _ok("Structural hazard cleared. Floor 3 entry remains prohibited.")

    _section("Incident Commander approves operational plan")
    if plans:
        log.approve_plan(
            plan_id=plan_id,
            incident_id=incident_id,
            approved_by=ic,
        )
        _ok(f"Plan {plan_id} approved by {ic.id}.")

    # -----------------------------------------------------------------------
    _banner("PHASE 6–9: RESUME — operations through closure")
    # -----------------------------------------------------------------------

    _section("Resuming pipeline from operations phase")
    resume_result = runner.resume(
        incident_id=incident_id,
        from_phase="operations-agent",
        authorized_by=ic,
    )

    _show("Phases completed", resume_result["phases_completed"])

    if resume_result["escalations"]:
        _section("Escalations raised during operations")
        for esc in resume_result["escalations"]:
            _escalation(
                f"Raised by: {esc.get('raised_by', '?')} "
                f"→ {esc.get('escalate_to', '?')}"
            )

    if resume_result["awaiting_human"]:
        _waiting(resume_result["awaiting_human"]["message"])

    if resume_result["blocks"]:
        for block in resume_result["blocks"]:
            _narrate(f"Pipeline halted at '{block['phase']}': {block['reason']}")

    # -----------------------------------------------------------------------
    _banner("FIELD OPERATIONS: extraction logged by field teams")
    # -----------------------------------------------------------------------

    _section("Team Alpha logs extraction start")
    log.log_action(
        incident_id=incident_id,
        action_type=ActionType.EXTRACTION_STARTED,
        source=ActionSource(type="human", id="Team-Alpha-Lead"),
        reference="radio-log-0412-1347",
        data={"victims": [v1_id, v2_id], "entry_point": "East stairwell, ground floor"},
    )
    _ok("Extraction started logged.")

    _section("Paramedic logs victim assessments")
    log.log_action(
        incident_id=incident_id,
        action_type=ActionType.VICTIM_ASSESSED,
        source=ActionSource(type="human", id="Paramedic-Torres"),
        reference="triage-report-0412-1349",
        data={"victim_id": v1_id, "triage_category": "immediate", "vitals": "conscious, breathing"},
    )
    log.log_action(
        incident_id=incident_id,
        action_type=ActionType.VICTIM_ASSESSED,
        source=ActionSource(type="human", id="Paramedic-Torres"),
        reference="triage-report-0412-1350",
        data={"victim_id": v2_id, "triage_category": "delayed", "vitals": "ambulatory, minor lacerations"},
    )
    _ok("Both victims assessed.")

    _section("Team Alpha logs extraction complete")
    log.log_action(
        incident_id=incident_id,
        action_type=ActionType.EXTRACTION_COMPLETE,
        source=ActionSource(type="human", id="Team-Alpha-Lead"),
        reference="radio-log-0412-1412",
        data={"victims_extracted": [v1_id, v2_id]},
    )
    _ok("Extraction complete logged.")

    _section("Paramedic logs victim stabilization")
    log.log_action(
        incident_id=incident_id,
        action_type=ActionType.VICTIM_STABILIZED,
        source=ActionSource(type="human", id="Paramedic-Torres"),
        reference="medical-report-0412-1415",
        data={"victim_id": v1_id},
    )
    log.log_action(
        incident_id=incident_id,
        action_type=ActionType.VICTIM_STABILIZED,
        source=ActionSource(type="human", id="Paramedic-Torres"),
        reference="medical-report-0412-1416",
        data={"victim_id": v2_id},
    )
    _ok("Both victims stabilized.")

    _section("Incident Commander authorizes transfer to hospital (human-only)")
    log.log_action(
        incident_id=incident_id,
        action_type=ActionType.VICTIM_TRANSFERRED,
        source=ic,
        reference="hospital-transfer-0412-1420",
        data={"victims": [v1_id, v2_id], "receiving_facility": "Mercy General ER"},
    )
    _ok("Victims transferred to medical care — logged by Incident Commander.")

    # -----------------------------------------------------------------------
    _banner("PHASE 8–9: VERIFICATION AND CLOSURE")
    # -----------------------------------------------------------------------

    _section("Resuming pipeline for verification and command roll-up")
    verify_result = runner.resume(
        incident_id=incident_id,
        from_phase="verification-agent",
        authorized_by=ic,
    )

    _show("Phases completed", verify_result["phases_completed"])

    if verify_result["escalations"]:
        for esc in verify_result["escalations"]:
            _escalation(
                f"Raised by: {esc.get('raised_by', '?')} "
                f"→ {esc.get('escalate_to', '?')}"
            )

    # Final closure — Incident Commander sign-off.
    _section("Incident Commander closes incident")
    log.log_action(
        incident_id=incident_id,
        action_type=ActionType.INCIDENT_CLOSED,
        source=ic,
        reference="incident-close-IC1-0412-1445",
        data={"summary": "All victims extracted and transferred. Scene cleared. No further casualties."},
    )
    _ok("Incident closed by Incident Commander.")

    log.log_action(
        incident_id=incident_id,
        action_type=ActionType.AFTER_ACTION_FILED,
        source=ActionSource(type="human", id="PlanningSection-Lead"),
        reference="aar-0412-1530",
        data={"report": "After-action report filed. Key finding: gas utility isolation delayed entry by 18 min."},
    )
    _ok("After-action report filed.")

    # -----------------------------------------------------------------------
    _banner("FINAL INCIDENT RECORD")
    # -----------------------------------------------------------------------

    record = log.get_incident(incident_id)
    _show("incident_id",     record["incident_id"])
    _show("incident_type",   record["incident_type"])
    _show("priority",        record["priority"])
    _show("current_status",  record["current_status"])
    _show("open_escalations", record["open_escalations"])
    _show("open_hazards",    record["open_hazards"])
    _show("total_actions",   len(record["actions"]))
    _show("victims",         len(record["victims"]))

    _section("Full action timeline")
    for action in record["actions"]:
        print(
            f"  {action['timestamp'][:19]}Z  "
            f"{action['action_type']:<35} "
            f"source={action['source']['type']}:{action['source']['id']}"
        )

    _section("Escalations log")
    for esc in record["escalations"]:
        status = "resolved" if esc["resolved"] else "OPEN"
        print(
            f"  [{status}] {esc['raised_by']!s:<30} → {esc['escalate_to']}"
        )

    _banner("DEMO COMPLETE")
    _narrate("Two intentional rejections demonstrated:")
    _narrate("  1. Agent plan approval attempt → UnauthorizedSourceError")
    _narrate("  2. Premature incident closure  → InvalidSequenceError")
    _narrate("")
    _narrate("Every human-only action was logged by a named human source.")
    _narrate("Every escalation named a specific role — no vague 'notify a human'.")
    _narrate("Status was derived from the action log — never stored directly.")
    print()


if __name__ == "__main__":
    run_demo()
