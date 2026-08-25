"""
Earthward Rescue Task Force — fleet runner.

Loads the agent fleet from agents/manifest.json and routes rescue
incidents through the appropriate agents in phase-ordered sequence.

Each "agent function" in this runner corresponds to one of the foundry
house agents re-mapped to its rescue equivalent:

  Traceability Agent     -> IncidentLogAgent    (records every action)
  CMM / Quality Agents   -> AssessmentAgent     (situational picture)
  Manufacturing Engineer -> PlanningAgent       (operational plan)
  Materials Engineer     -> ResourceAgent       (personnel & equipment)
  Forge Agents           -> OperationsAgent     (field deployment)
  Assembly Agents        -> IntegrationAgent    (team coordination)
  Validation Agents      -> VerificationAgent   (objective achieved?)
  EHS Agent              -> SafetyAgent         (personnel accountability)
  Program Mgmt Agent     -> CommandAgent        (cross-team status)

The runner enforces the same four cross-cutting rules as every foundry agent:
  1. No agent self-certifies its own output.
  2. No agent hides a failure to look complete.
  3. No agent invents a standard or authorization.
  4. Every escalation names who it goes to.

Usage:
    from runner import TaskForceRunner
    from models import ActionSource, IncidentType, IncidentPriority

    runner = TaskForceRunner()
    result = runner.intake(
        incident_type=IncidentType.URBAN_SAR,
        priority=IncidentPriority.LIFE_THREAT,
        location="123 Main St — building collapse, 3 floors",
        description="Partial structural collapse, 2 confirmed trapped, gas leak reported",
        reported_by=ActionSource(type="human", id="Dispatcher-IC1"),
    )
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import incident_log as log
from models import (
    ActionSource,
    ActionType,
    IncidentPriority,
    IncidentType,
    RescueError,
    UnauthorizedSourceError,
    HazardBlockError,
    InvalidSequenceError,
)

logger = logging.getLogger("earthward.rescue.runner")

# ---------------------------------------------------------------------------
# Manifest loader
# ---------------------------------------------------------------------------

_MANIFEST_PATH = Path(__file__).parent.parent.parent / "agents" / "manifest.json"


def _load_manifest() -> dict[str, Any]:
    with open(_MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Agent function registry
# Maps rescue function names to their handler methods.
# Adding a new agent = add a method + register it here.
# ---------------------------------------------------------------------------

class TaskForceRunner:
    """
    Routes an incident through the rescue agent fleet in phase order.

    Phase 1  — Incident Log Agent    (records spine; always runs first)
    Phase 2  — Safety Agent          (hazard sweep before any operations)
    Phase 3  — Assessment Agent      (situational picture)
    Phase 4  — Resource Agent        (what do we have available)
    Phase 5  — Planning Agent        (draft operational plan)
    Phase 6  — Operations Agent      (deploy teams — requires human plan approval)
    Phase 7  — Integration Agent     (coordinate across teams)
    Phase 8  — Verification Agent    (confirm objective achieved)
    Phase 9  — Command Agent         (cross-team status roll-up)

    Each phase returns a result dict. Escalations and blocks are surfaced
    explicitly — never swallowed. The runner halts the pipeline and returns
    the block if a hard stop is encountered.
    """

    def __init__(self):
        self.manifest = _load_manifest()
        self._pipeline: list[tuple[str, callable]] = [
            ("incident-log-agent",   self._run_incident_log),
            ("safety-agent",         self._run_safety),
            ("assessment-agent",     self._run_assessment),
            ("resource-agent",       self._run_resource),
            ("planning-agent",       self._run_planning),
            # Phases 6-9 require human approval gates — they are registered
            # but the runner will surface the approval requirement rather
            # than auto-proceeding.
            ("operations-agent",     self._run_operations),
            ("integration-agent",    self._run_integration),
            ("verification-agent",   self._run_verification),
            ("command-agent",        self._run_command),
        ]
        # Phases that require human approval before the runner proceeds.
        self._human_gates: set[str] = {
            "operations-agent",     # requires plan approval
            "verification-agent",   # requires extraction complete
        }

    # -----------------------------------------------------------------------
    # Primary entry point
    # -----------------------------------------------------------------------

    def intake(
        self,
        incident_type: IncidentType,
        priority: IncidentPriority,
        location: str,
        description: str,
        reported_by: ActionSource,
        incident_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Open a new incident and run it through the full pipeline up to
        the first human gate or hard block.

        Returns the pipeline result — which phase it reached, what it
        produced, and what (if anything) is waiting for human action.
        """
        # Phase 1 always runs first — open the incident and start the log.
        incident_id = log.open_incident(
            incident_type=incident_type,
            priority=priority,
            location=location,
            description=description,
            source=reported_by,
            incident_id=incident_id,
        )

        result: dict[str, Any] = {
            "incident_id": incident_id,
            "phases_completed": [],
            "current_phase": None,
            "awaiting_human": None,
            "escalations": [],
            "blocks": [],
            "outputs": {},
        }

        for agent_name, handler in self._pipeline[1:]:  # skip incident-log; already run
            result["current_phase"] = agent_name

            # Check if this phase requires a human gate that hasn't been
            # cleared — surface it and halt rather than auto-proceeding.
            if agent_name in self._human_gates:
                gate_cleared, gate_message = self._check_human_gate(
                    agent_name, incident_id
                )
                if not gate_cleared:
                    result["awaiting_human"] = {
                        "phase": agent_name,
                        "message": gate_message,
                    }
                    logger.info(
                        "incident=%s phase=%s awaiting_human message=%r",
                        incident_id, agent_name, gate_message,
                    )
                    break

            try:
                phase_output = handler(incident_id, reported_by)
                result["phases_completed"].append(agent_name)
                result["outputs"][agent_name] = phase_output

                # Surface any escalations this phase raised.
                if phase_output.get("escalations"):
                    result["escalations"].extend(phase_output["escalations"])

                # If the phase itself says halt, stop the pipeline.
                if phase_output.get("halt"):
                    halt_reason = phase_output.get("halt_reason", "unspecified")
                    result["blocks"].append({
                        "phase": agent_name,
                        "reason": halt_reason,
                    })
                    logger.warning(
                        "incident=%s phase=%s halt reason=%r",
                        incident_id, agent_name, halt_reason,
                    )
                    break

            except HazardBlockError as e:
                result["blocks"].append({"phase": agent_name, "reason": str(e)})
                logger.warning("incident=%s phase=%s hazard_block reason=%r", incident_id, agent_name, str(e))
                esc_id = log.raise_escalation(
                    incident_id=incident_id,
                    raised_by=agent_name,
                    escalate_to="Safety Officer",
                    reason=str(e),
                    action_required="Clear all critical/high hazards before operations resume.",
                )
                result["escalations"].append({
                    "escalation_id": esc_id,
                    "raised_by": agent_name,
                    "escalate_to": "Safety Officer",
                    "reason": str(e),
                })
                logger.info(
                    "incident=%s phase=%s escalation_id=%s escalate_to=Safety Officer",
                    incident_id, agent_name, esc_id,
                )
                break

            except InvalidSequenceError as e:
                result["blocks"].append({"phase": agent_name, "reason": str(e)})
                logger.warning("incident=%s phase=%s invalid_sequence reason=%r", incident_id, agent_name, str(e))
                break

            except UnauthorizedSourceError as e:
                # This should never happen in the runner — surfaces a
                # configuration error clearly rather than silently failing.
                result["blocks"].append({
                    "phase": agent_name,
                    "reason": f"CONFIGURATION ERROR — unauthorized source: {e}",
                })
                logger.error("incident=%s phase=%s configuration_error unauthorized_source=%r", incident_id, agent_name, str(e))
                break

            except RescueError as e:
                result["blocks"].append({"phase": agent_name, "reason": str(e)})
                logger.warning("incident=%s phase=%s rescue_error reason=%r", incident_id, agent_name, str(e))
                break

        return result

    def resume(
        self,
        incident_id: str,
        from_phase: str,
        authorized_by: ActionSource,
    ) -> dict[str, Any]:
        """
        Resume the pipeline from a named phase after a human gate has been
        cleared. authorized_by must be a human source.

        Used after: plan approval, hazard clearance, extraction confirmation.
        """
        if not authorized_by.is_human():
            raise UnauthorizedSourceError(
                "Pipeline resume requires a human source. "
                f"Got source.type={authorized_by.type!r} (id={authorized_by.id!r})."
            )

        result: dict[str, Any] = {
            "incident_id": incident_id,
            "resumed_from": from_phase,
            "phases_completed": [],
            "awaiting_human": None,
            "escalations": [],
            "blocks": [],
            "outputs": {},
        }

        # Find the phase index to resume from.
        phase_names = [name for name, _ in self._pipeline]
        try:
            start_idx = phase_names.index(from_phase)
        except ValueError:
            raise RescueError(f"Unknown phase: {from_phase!r}. Valid phases: {phase_names}")

        for agent_name, handler in self._pipeline[start_idx:]:
            result["current_phase"] = agent_name

            if agent_name in self._human_gates:
                gate_cleared, gate_message = self._check_human_gate(
                    agent_name, incident_id
                )
                if not gate_cleared:
                    result["awaiting_human"] = {
                        "phase": agent_name,
                        "message": gate_message,
                    }
                    logger.info(
                        "incident=%s phase=%s resume_awaiting_human message=%r",
                        incident_id, agent_name, gate_message,
                    )
                    break

            try:
                phase_output = handler(incident_id, authorized_by)
                result["phases_completed"].append(agent_name)
                result["outputs"][agent_name] = phase_output

                if phase_output.get("escalations"):
                    result["escalations"].extend(phase_output["escalations"])

                if phase_output.get("halt"):
                    halt_reason = phase_output.get("halt_reason", "unspecified")
                    result["blocks"].append({
                        "phase": agent_name,
                        "reason": halt_reason,
                    })
                    logger.warning(
                        "incident=%s phase=%s resume_halt reason=%r",
                        incident_id, agent_name, halt_reason,
                    )
                    break

            except (HazardBlockError, InvalidSequenceError, RescueError) as e:
                result["blocks"].append({"phase": agent_name, "reason": str(e)})
                logger.warning(
                    "incident=%s phase=%s resume_error type=%s reason=%r",
                    incident_id, agent_name, type(e).__name__, str(e),
                )
                break

        return result

    # -----------------------------------------------------------------------
    # Human gate checks
    # -----------------------------------------------------------------------

    def _check_human_gate(
        self, agent_name: str, incident_id: str
    ) -> tuple[bool, str]:
        """
        Returns (cleared, message). If not cleared, message explains what
        human action is required before this phase can run.
        """
        record = log.get_incident(incident_id)
        action_types = {a["action_type"] for a in record["actions"]}

        if agent_name == "operations-agent":
            if ActionType.OPERATIONAL_PLAN_APPROVED.value not in action_types:
                return False, (
                    "Operations phase requires a human-approved operational plan. "
                    "Escalate to Incident Commander for plan review and approval."
                )

        if agent_name == "verification-agent":
            if ActionType.EXTRACTION_COMPLETE.value not in action_types:
                return False, (
                    "Verification phase requires extraction complete to be logged. "
                    "Confirm with Operations Section Chief before proceeding."
                )

        return True, ""

    # -----------------------------------------------------------------------
    # Phase handlers
    # -----------------------------------------------------------------------

    def _run_incident_log(
        self, incident_id: str, source: ActionSource
    ) -> dict[str, Any]:
        """
        Phase 1 — Incident Log Agent (Records house equivalent).
        Confirm the incident record is open and the log is active.
        """
        record = log.get_incident(incident_id)
        return {
            "status": "log_active",
            "incident_id": incident_id,
            "current_status": record["current_status"],
            "action_count": len(record["actions"]),
        }

    def _run_safety(
        self, incident_id: str, source: ActionSource
    ) -> dict[str, Any]:
        """
        Phase 2 — Safety Agent (EHS house equivalent).
        Sweep for known hazard types based on incident type and priority.
        Flags are advisory — only a human can clear a hazard.
        Never self-certifies the scene as safe.
        """
        record = log.get_incident(incident_id)
        incident_type = record["incident_type"]

        # Known hazard patterns per incident type.
        hazard_flags: list[dict] = []
        known_hazards = _known_hazard_flags(incident_type)

        for hazard in known_hazards:
            hazard_flags.append({
                "flag": hazard["flag"],
                "severity": hazard["severity"],
                "action": hazard["action"],
                "requires_human_clearance": True,
            })

        escalations = []
        if any(h["severity"] in ("critical", "high") for h in known_hazards):
            esc_id = log.raise_escalation(
                incident_id=incident_id,
                raised_by="safety-agent",
                escalate_to="Safety Officer",
                reason=(
                    f"Incident type '{incident_type}' carries known critical/high hazard flags. "
                    "Scene safety not confirmed."
                ),
                action_required=(
                    "Safety Officer must assess and clear each flagged hazard "
                    "before operations proceed."
                ),
            )
            escalations.append({
                "escalation_id": esc_id,
                "raised_by": "safety-agent",
                "escalate_to": "Safety Officer",
            })

        # Log a situation report to mark assessment started.
        log.log_action(
            incident_id=incident_id,
            action_type=ActionType.SITUATION_REPORT,
            source=ActionSource(type="agent", id="safety-agent"),
            reference=f"safety-sweep-{incident_id[:8]}",
            data={"hazard_flags": hazard_flags},
        )

        return {
            "status": "safety_sweep_complete",
            "hazard_flags": hazard_flags,
            "escalations": escalations,
            "note": (
                "Safety Agent does not certify scene safety. "
                "Each flagged hazard requires human assessment and sign-off."
            ),
        }

    def _run_assessment(
        self, incident_id: str, source: ActionSource
    ) -> dict[str, Any]:
        """
        Phase 3 — Assessment Agent (Metrology house equivalent).
        Structures the situational picture from known incident data.
        Reports gaps explicitly — never fills them with assumptions.
        """
        record = log.get_incident(incident_id)

        gaps: list[str] = []
        if not record["victims"]:
            gaps.append("No confirmed victims logged — victim count and location unverified.")
        if not record["hazards"]:
            gaps.append("No hazards logged — structural/environmental assessment pending.")

        log.log_action(
            incident_id=incident_id,
            action_type=ActionType.SITUATION_REPORT,
            source=ActionSource(type="agent", id="assessment-agent"),
            reference=f"assessment-{incident_id[:8]}",
            data={
                "victim_count": len(record["victims"]),
                "open_hazards": record["open_hazards"],
                "gaps": gaps,
            },
        )

        escalations = []
        if gaps:
            esc_id = log.raise_escalation(
                incident_id=incident_id,
                raised_by="assessment-agent",
                escalate_to="Operations Section Chief",
                reason="Situational assessment has unresolved gaps.",
                action_required=(
                    "Operations Section Chief to direct teams to close "
                    "information gaps before operational plan is finalized."
                ),
            )
            escalations.append({
                "escalation_id": esc_id,
                "raised_by": "assessment-agent",
                "escalate_to": "Operations Section Chief",
                "gaps": gaps,
            })

        return {
            "status": "assessment_complete",
            "victim_count": len(record["victims"]),
            "open_hazards": record["open_hazards"],
            "gaps": gaps,
            "escalations": escalations,
            "note": "Assessment Agent reports gaps as gaps. No assumptions made.",
        }

    def _run_resource(
        self, incident_id: str, source: ActionSource
    ) -> dict[str, Any]:
        """
        Phase 4 — Resource Agent (Materials house equivalent).
        Identifies resource requirements from incident profile.
        Does not commit resources — requests only, pending human assignment.
        """
        record = log.get_incident(incident_id)
        incident_type = record["incident_type"]
        priority = record["priority"]

        required = _resource_requirements(incident_type, priority)

        log.log_action(
            incident_id=incident_id,
            action_type=ActionType.RESOURCE_REQUESTED,
            source=ActionSource(type="agent", id="resource-agent"),
            reference=f"resource-req-{incident_id[:8]}",
            data={"required_resources": required},
        )

        escalations = []
        esc_id = log.raise_escalation(
            incident_id=incident_id,
            raised_by="resource-agent",
            escalate_to="Logistics Section Chief",
            reason="Resource requirements identified for incident.",
            action_required=(
                "Logistics Section Chief to confirm availability and "
                "assign resources. Resource Agent does not commit resources."
            ),
        )
        escalations.append({
            "escalation_id": esc_id,
            "raised_by": "resource-agent",
            "escalate_to": "Logistics Section Chief",
            "required_resources": required,
        })

        return {
            "status": "resource_requirements_drafted",
            "required_resources": required,
            "escalations": escalations,
            "note": "Resource Agent drafts requirements only. Human Logistics assigns.",
        }

    def _run_planning(
        self, incident_id: str, source: ActionSource
    ) -> dict[str, Any]:
        """
        Phase 5 — Planning Agent (Manufacturing Engineer equivalent).
        Drafts an operational plan — always marked draft.
        Approval is human-only; plan never self-approves.
        Assumptions are always listed explicitly, never folded in silently.
        """
        record = log.get_incident(incident_id)

        objectives = _derive_objectives(record)
        assumptions = [
            "Victim count and locations as reported — not independently verified by this agent.",
            "Resource availability as requested — confirmation pending from Logistics.",
            "Hazard flags are advisory until cleared by Safety Officer.",
        ]
        open_questions = []
        if not record["victims"]:
            open_questions.append("Victim count and exact location not confirmed.")
        if record["open_hazards"] > 0:
            open_questions.append(
                f"{record['open_hazards']} critical/high hazard(s) not yet cleared."
            )

        plan_id = log.draft_plan(
            incident_id=incident_id,
            drafted_by="planning-agent",
            objectives=objectives,
            team_assignments={},   # Logistics fills in actuals after approval.
            resource_assignments={},
            assumptions=assumptions,
            open_questions=open_questions,
        )

        esc_id = log.raise_escalation(
            incident_id=incident_id,
            raised_by="planning-agent",
            escalate_to="Incident Commander",
            reason="Operational plan drafted and ready for review.",
            action_required=(
                "Incident Commander to review plan, resolve open questions, "
                "and approve before operations phase begins."
            ),
        )

        return {
            "status": "plan_drafted",
            "plan_id": plan_id,
            "objectives": objectives,
            "assumptions": assumptions,
            "open_questions": open_questions,
            "escalations": [{
                "escalation_id": esc_id,
                "raised_by": "planning-agent",
                "escalate_to": "Incident Commander",
            }],
            "note": "Plan is DRAFT. Incident Commander approval required before operations.",
            # Signal the pipeline to pause here — plan approval is a human gate.
            "halt": True,
            "halt_reason": (
                "Operational plan requires Incident Commander approval. "
                "Call runner.resume() after plan is approved."
            ),
        }

    def _run_operations(
        self, incident_id: str, source: ActionSource
    ) -> dict[str, Any]:
        """
        Phase 6 — Operations Agent (Forge house equivalent).
        Sequences field deployment. Only runs after plan approval (human gate).
        Logs TEAM_DEPLOYED — never marks the operation complete itself.
        """
        record = log.get_incident(incident_id)

        # Get the approved plan.
        approved_plans = [p for p in record["operational_plans"] if p["status"] == "approved"]
        if not approved_plans:
            raise InvalidSequenceError(
                "Operations phase reached without an approved plan — this should "
                "have been caught by the human gate. Configuration error."
            )
        plan = approved_plans[-1]

        log.log_action(
            incident_id=incident_id,
            action_type=ActionType.TEAM_DEPLOYED,
            source=ActionSource(type="agent", id="operations-agent"),
            reference=f"plan-{plan['plan_id']}",
            data={"plan_id": plan["plan_id"], "objectives": plan["objectives"]},
        )

        return {
            "status": "teams_deployed",
            "plan_id": plan["plan_id"],
            "objectives": plan["objectives"],
            "note": (
                "Operations Agent sequences deployment. "
                "Extraction status logged by field teams via log_action()."
            ),
        }

    def _run_integration(
        self, incident_id: str, source: ActionSource
    ) -> dict[str, Any]:
        """
        Phase 7 — Integration Agent (Assembly house equivalent).
        Checks team-to-objective coverage. Reports gaps — never assumes coverage.
        """
        record = log.get_incident(incident_id)
        approved_plans = [p for p in record["operational_plans"] if p["status"] == "approved"]

        if not approved_plans:
            return {
                "status": "no_approved_plan",
                "note": "Integration Agent has no approved plan to check coverage against.",
            }

        plan = approved_plans[-1]
        unassigned_objectives = [
            obj for obj in plan["objectives"]
            if obj not in plan.get("team_assignments", {}).values()
        ]

        escalations = []
        if unassigned_objectives:
            esc_id = log.raise_escalation(
                incident_id=incident_id,
                raised_by="integration-agent",
                escalate_to="Operations Section Chief",
                reason="One or more objectives have no assigned team.",
                action_required=(
                    f"Assign teams to: {unassigned_objectives}. "
                    "Integration Agent does not make assignments."
                ),
            )
            escalations.append({
                "escalation_id": esc_id,
                "raised_by": "integration-agent",
                "escalate_to": "Operations Section Chief",
                "unassigned": unassigned_objectives,
            })

        return {
            "status": "integration_check_complete",
            "unassigned_objectives": unassigned_objectives,
            "escalations": escalations,
            "note": "Integration Agent reports coverage gaps. Does not make assignments.",
        }

    def _run_verification(
        self, incident_id: str, source: ActionSource
    ) -> dict[str, Any]:
        """
        Phase 8 — Verification Agent (Validation house equivalent).
        Checks that objectives are met against logged evidence.
        Never self-validates — surfaces mismatches for human review.
        """
        record = log.get_incident(incident_id)
        action_types = {a["action_type"] for a in record["actions"]}

        unverified: list[str] = []

        # Check victims: use the action log for extraction evidence,
        # not the victims table (extracted_at is not set via log_action).
        victim_count = len(record["victims"])
        extraction_complete_logged = ActionType.EXTRACTION_COMPLETE.value in action_types
        if victim_count > 0 and not extraction_complete_logged:
            unverified.append(
                f"{victim_count} victim(s) logged but extraction_complete not yet recorded."
            )

        if record["open_hazards"] > 0:
            unverified.append(
                f"{record['open_hazards']} critical/high hazard(s) still open."
            )

        if not unverified:
            log.log_action(
                incident_id=incident_id,
                action_type=ActionType.OBJECTIVE_VERIFIED,
                source=ActionSource(type="agent", id="verification-agent"),
                reference=f"verification-{incident_id[:8]}",
                data={"verified_against": "incident_action_log"},
            )

        escalations = []
        if unverified:
            esc_id = log.raise_escalation(
                incident_id=incident_id,
                raised_by="verification-agent",
                escalate_to="Operations Section Chief",
                reason="Objectives not fully verified — evidence gaps remain.",
                action_required=(
                    f"Resolve before incident closure: {unverified}"
                ),
            )
            escalations.append({
                "escalation_id": esc_id,
                "raised_by": "verification-agent",
                "escalate_to": "Operations Section Chief",
                "unverified": unverified,
            })

        return {
            "status": "objectives_verified" if not unverified else "verification_incomplete",
            "unverified_items": unverified,
            "escalations": escalations,
            "note": (
                "Verification Agent does not self-validate. "
                "Incident closure requires human Incident Commander sign-off."
            ),
        }

    def _run_command(
        self, incident_id: str, source: ActionSource
    ) -> dict[str, Any]:
        """
        Phase 9 — Command Agent (Foundry General Manager equivalent).
        Cross-team status roll-up. Surfaces blockers and open escalations.
        Never resolves conflicts itself — routes to named humans.
        """
        record = log.get_incident(incident_id)

        open_escalations = [e for e in record["escalations"] if not e["resolved"]]
        open_hazards = [h for h in record["hazards"] if h["is_open"]]

        return {
            "status": "command_rollup_complete",
            "incident_status": record["current_status"],
            "open_escalations": len(open_escalations),
            "open_hazards": len(open_hazards),
            "escalation_details": open_escalations,
            "note": (
                "Command Agent reports status only. "
                "All decisions route to named human commanders."
            ),
        }


# ---------------------------------------------------------------------------
# Incident-type knowledge tables
# These encode known hazard patterns and resource profiles per incident type.
# Agents reference these — they do not invent them.
# ---------------------------------------------------------------------------

def _known_hazard_flags(incident_type: str) -> list[dict]:
    """Known hazard patterns per incident type — referenced, not invented."""
    patterns: dict[str, list[dict]] = {
        "urban_sar": [
            {"flag": "Structural instability — secondary collapse risk", "severity": "critical",
             "action": "Structural Specialist assessment before entry"},
            {"flag": "Utility hazards — gas, electrical", "severity": "critical",
             "action": "Utilities isolated and confirmed by Utility Control Officer"},
            {"flag": "Dust/particulate inhalation", "severity": "high",
             "action": "Respiratory protection required"},
        ],
        "wilderness_sar": [
            {"flag": "Terrain hazard — fall risk, unstable ground", "severity": "high",
             "action": "Route assessment before team deployment"},
            {"flag": "Environmental exposure — temperature, weather", "severity": "moderate",
             "action": "Weather and time-on-mission assessment"},
        ],
        "disaster": [
            {"flag": "Floodwater — contamination, current, depth unknown", "severity": "critical",
             "action": "Water rescue assessment before entry"},
            {"flag": "Infrastructure damage — road, bridge integrity", "severity": "high",
             "action": "Engineer or structural assessment before approach"},
        ],
        "maritime": [
            {"flag": "Water temperature — hypothermia risk", "severity": "critical",
             "action": "Water temperature logged, survival time estimated"},
            {"flag": "Vessel stability — sinking/capsized risk", "severity": "critical",
             "action": "Vessel stability assessment before boarding"},
        ],
        "hazmat": [
            {"flag": "Unknown substance — toxicity unconfirmed", "severity": "critical",
             "action": "HazMat Specialist identification before approach"},
            {"flag": "Contamination zone — hot/warm/cold zone boundaries undefined", "severity": "critical",
             "action": "Zone demarcation by qualified HazMat Officer"},
        ],
        "medical_mass_cas": [
            {"flag": "Triage capacity — casualty count may exceed resource", "severity": "high",
             "action": "Medical Branch Director to assess surge capacity"},
            {"flag": "Scene security — secondary event possible", "severity": "high",
             "action": "Law enforcement confirmation before medical entry"},
        ],
    }
    return patterns.get(incident_type, [
        {"flag": "Incident type-specific hazards not catalogued — manual assessment required",
         "severity": "high", "action": "Safety Officer manual scene assessment"},
    ])


def _resource_requirements(incident_type: str, priority: str) -> list[dict]:
    """Minimum resource profiles per incident type and priority."""
    base: dict[str, list[dict]] = {
        "urban_sar": [
            {"resource_type": "rescue_team",      "minimum": 2, "note": "Technical rescue certified"},
            {"resource_type": "medical_unit",     "minimum": 1, "note": "ALS capable"},
            {"resource_type": "heavy_equipment",  "minimum": 1, "note": "For debris removal"},
            {"resource_type": "canine_team",      "minimum": 1, "note": "Live-find certified"},
            {"resource_type": "command_post",     "minimum": 1, "note": "ICS Type 3 minimum"},
        ],
        "wilderness_sar": [
            {"resource_type": "rescue_team",      "minimum": 1, "note": "Wilderness SAR certified"},
            {"resource_type": "medical_unit",     "minimum": 1, "note": "Wilderness medicine capable"},
            {"resource_type": "aerial_asset",     "minimum": 1, "note": "If terrain requires"},
        ],
        "disaster": [
            {"resource_type": "rescue_team",      "minimum": 3, "note": "Multi-discipline"},
            {"resource_type": "medical_unit",     "minimum": 2, "note": "Mass casualty capable"},
            {"resource_type": "heavy_equipment",  "minimum": 2, "note": "Access and debris"},
            {"resource_type": "command_post",     "minimum": 1, "note": "Unified command capable"},
        ],
        "maritime": [
            {"resource_type": "water_rescue",     "minimum": 1, "note": "Swift water or dive as required"},
            {"resource_type": "medical_unit",     "minimum": 1, "note": "Hypothermia protocol capable"},
            {"resource_type": "aerial_asset",     "minimum": 1, "note": "Hoist-capable if available"},
        ],
        "hazmat": [
            {"resource_type": "hazmat_unit",      "minimum": 1, "note": "Level A/B as indicated"},
            {"resource_type": "medical_unit",     "minimum": 1, "note": "Decontamination capable"},
            {"resource_type": "rescue_team",      "minimum": 1, "note": "HazMat rescue certified"},
        ],
        "medical_mass_cas": [
            {"resource_type": "medical_unit",     "minimum": 3, "note": "ALS + triage capability"},
            {"resource_type": "rescue_team",      "minimum": 2, "note": "Extraction support"},
            {"resource_type": "command_post",     "minimum": 1, "note": "Medical Branch Director on site"},
        ],
    }
    resources = base.get(incident_type, [
        {"resource_type": "rescue_team", "minimum": 1, "note": "Minimum — type-specific assessment required"}
    ])

    # Life threat priority doubles the minimum staffing.
    if priority == "life_threat":
        for r in resources:
            r["minimum"] = r["minimum"] * 2
            r["note"] += " [doubled for life_threat priority]"

    return resources


def _derive_objectives(record: dict) -> list[str]:
    """Derive operational objectives from the incident record."""
    objectives = []
    incident_type = record["incident_type"]

    if incident_type == "urban_sar":
        objectives.append("Confirm and mark structural safe entry/exit routes.")
        objectives.append("Locate all confirmed and suspected victims.")
    elif incident_type == "wilderness_sar":
        objectives.append("Establish last known position and search grid.")
        objectives.append("Deploy search teams on prioritized probability zones.")
    elif incident_type == "disaster":
        objectives.append("Assess and establish access routes to affected area.")
        objectives.append("Conduct primary search of highest-probability areas.")
    elif incident_type == "maritime":
        objectives.append("Establish vessel/victim position and drift estimate.")
        objectives.append("Deploy water rescue assets to victim location.")
    elif incident_type == "hazmat":
        objectives.append("Identify substance and establish exclusion zones.")
        objectives.append("Account for all personnel inside the hazard area.")
    elif incident_type == "medical_mass_cas":
        objectives.append("Establish triage, treatment, and transport areas.")
        objectives.append("Initiate START triage on all accessible casualties.")
    else:
        objectives.append("Assess scene and establish incident objectives with Incident Commander.")

    if record["victims"]:
        objectives.append(
            f"Extract and transfer {len(record['victims'])} confirmed victim(s) to medical care."
        )

    objectives.append("Account for all rescue personnel throughout operation.")
    objectives.append("Conduct after-action debrief and file incident report.")

    return objectives
