"""
Regression tests for the Rescue service's incident log service
(incident_log.py).
Run: python3 tests/test_incident_log.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import incident_log as log
from models import (
    ActionSource,
    ActionType,
    HUMAN_ONLY_ACTION_TYPES,
    HazardBlockError,
    IncidentPriority,
    IncidentType,
    MissingReferenceError,
    UnauthorizedSourceError,
    UnknownIncidentError,
)


def setup_incident(**overrides):
    log.init_db(reset=True)
    defaults = dict(
        incident_type=IncidentType.URBAN_SAR,
        priority=IncidentPriority.LIFE_THREAT,
        location="123 Main St",
        description="structural collapse",
        source=ActionSource("human", "h1"),
    )
    defaults.update(overrides)
    return log.open_incident(**defaults)


# ---------------------------------------------------------------------------
# open_incident
# ---------------------------------------------------------------------------

def test_open_incident_happy_path():
    incident_id = setup_incident()
    rec = log.get_incident(incident_id)
    assert rec["incident_id"] == incident_id
    assert rec["incident_type"] == IncidentType.URBAN_SAR.value
    assert rec["priority"] == IncidentPriority.LIFE_THREAT.value
    action_types = [a["action_type"] for a in rec["actions"]]
    assert ActionType.INCIDENT_OPENED.value in action_types
    assert rec["current_status"] == "reported"


# ---------------------------------------------------------------------------
# log_action happy path
# ---------------------------------------------------------------------------

def test_log_action_happy_path_agent_non_human_only():
    incident_id = setup_incident()
    result = log.log_action(
        incident_id, ActionType.SITUATION_REPORT,
        source=ActionSource("agent", "assessment-agent"), reference="SR-1",
    )
    assert result["action_type"] == ActionType.SITUATION_REPORT.value
    rec = log.get_incident(incident_id)
    assert rec["current_status"] == "assessing"


# ---------------------------------------------------------------------------
# log_action raises UnauthorizedSourceError for agent on human-only types
# ---------------------------------------------------------------------------

def test_log_action_agent_cannot_approve_plan():
    incident_id = setup_incident()
    log.log_action(incident_id, ActionType.OPERATIONAL_PLAN_DRAFTED,
                    source=ActionSource("agent", "a1"), reference="PLAN-1")
    try:
        log.log_action(
            incident_id, ActionType.OPERATIONAL_PLAN_APPROVED,
            source=ActionSource("agent", "sneaky"), reference="PLAN-1",
        )
        assert False, "should have raised UnauthorizedSourceError"
    except UnauthorizedSourceError:
        pass


def test_log_action_agent_cannot_clear_hazard():
    incident_id = setup_incident()
    log.log_action(incident_id, ActionType.HAZARD_OPENED,
                    source=ActionSource("agent", "a1"), reference="HZ-1")
    try:
        log.log_action(
            incident_id, ActionType.HAZARD_CLEARED,
            source=ActionSource("agent", "sneaky"), reference="HZ-1",
        )
        assert False, "should have raised UnauthorizedSourceError"
    except UnauthorizedSourceError:
        pass


def test_log_action_agent_cannot_close_incident():
    incident_id = setup_incident()
    try:
        log.log_action(
            incident_id, ActionType.INCIDENT_CLOSED,
            source=ActionSource("agent", "sneaky"), reference="CLOSE-1",
        )
        assert False, "should have raised UnauthorizedSourceError"
    except UnauthorizedSourceError:
        pass


def test_log_action_all_human_only_types_reject_agent_source():
    """Every action_type in HUMAN_ONLY_ACTION_TYPES rejects an agent source
    with UnauthorizedSourceError — checked before sequencing, so no
    prerequisite setup is needed to observe the rejection."""
    incident_id = setup_incident()
    for action_type in HUMAN_ONLY_ACTION_TYPES:
        try:
            log.log_action(
                incident_id, action_type,
                source=ActionSource("agent", "sneaky"), reference="REF-1",
            )
            assert False, f"should have raised UnauthorizedSourceError for {action_type.value}"
        except UnauthorizedSourceError:
            pass


# ---------------------------------------------------------------------------
# open_hazard + clear_hazard
# ---------------------------------------------------------------------------

def test_open_hazard_happy_path():
    incident_id = setup_incident()
    hazard_id = log.open_hazard(
        incident_id, description="gas leak", severity="critical",
        source=ActionSource("agent", "a1"),
    )
    rec = log.get_incident(incident_id)
    assert any(h["hazard_id"] == hazard_id for h in rec["hazards"])
    assert rec["open_hazards"] == 1
    assert rec["current_status"] == "hazard_blocked"


def test_clear_hazard_by_agent_rejected_by_human_succeeds():
    incident_id = setup_incident()
    hazard_id = log.open_hazard(
        incident_id, description="gas leak", severity="critical",
        source=ActionSource("agent", "a1"),
    )
    try:
        log.clear_hazard(incident_id, hazard_id, source=ActionSource("agent", "sneaky"))
        assert False, "should have raised UnauthorizedSourceError"
    except UnauthorizedSourceError:
        pass

    # Human can clear it.
    log.clear_hazard(incident_id, hazard_id, source=ActionSource("human", "h1"))
    rec = log.get_incident(incident_id)
    hazard = next(h for h in rec["hazards"] if h["hazard_id"] == hazard_id)
    assert hazard["is_open"] is False
    assert rec["open_hazards"] == 0


# ---------------------------------------------------------------------------
# HazardBlockError — read the source: it only fires for action types in
# _HAZARD_BLOCKED_ACTIONS (team_deployed, extraction_started,
# victim_transferred, incident_closed) AND only once the sequencing
# preconditions for that action type are already satisfied (sequencing is
# checked first in _check_sequence, hazard block second).
# ---------------------------------------------------------------------------

def test_hazard_block_prevents_team_deployed():
    incident_id = setup_incident()
    log.log_action(incident_id, ActionType.OPERATIONAL_PLAN_DRAFTED,
                    source=ActionSource("agent", "a1"), reference="PLAN-1")
    log.log_action(incident_id, ActionType.OPERATIONAL_PLAN_APPROVED,
                    source=ActionSource("human", "h1"), reference="PLAN-1")
    log.open_hazard(incident_id, description="unstable structure", severity="high",
                     source=ActionSource("agent", "a1"))
    try:
        log.log_action(incident_id, ActionType.TEAM_DEPLOYED,
                        source=ActionSource("agent", "a1"), reference="DEPLOY-1")
        assert False, "should have raised HazardBlockError"
    except HazardBlockError:
        pass


def test_hazard_block_does_not_prevent_unrelated_action():
    """HazardBlockError only guards the specific action types listed in
    _HAZARD_BLOCKED_ACTIONS. An open critical hazard does NOT block, e.g.,
    logging a SITUATION_REPORT, even though current_status reports
    hazard_blocked."""
    incident_id = setup_incident()
    log.open_hazard(incident_id, description="unstable structure", severity="critical",
                     source=ActionSource("agent", "a1"))
    result = log.log_action(incident_id, ActionType.SITUATION_REPORT,
                             source=ActionSource("agent", "a1"), reference="SR-1")
    assert result["action_type"] == ActionType.SITUATION_REPORT.value


def test_hazard_block_cleared_once_hazard_resolved():
    incident_id = setup_incident()
    log.log_action(incident_id, ActionType.OPERATIONAL_PLAN_DRAFTED,
                    source=ActionSource("agent", "a1"), reference="PLAN-1")
    log.log_action(incident_id, ActionType.OPERATIONAL_PLAN_APPROVED,
                    source=ActionSource("human", "h1"), reference="PLAN-1")
    hazard_id = log.open_hazard(incident_id, description="unstable structure", severity="high",
                                 source=ActionSource("agent", "a1"))
    try:
        log.log_action(incident_id, ActionType.TEAM_DEPLOYED,
                        source=ActionSource("agent", "a1"), reference="DEPLOY-1")
        assert False, "should have raised HazardBlockError"
    except HazardBlockError:
        pass
    log.clear_hazard(incident_id, hazard_id, source=ActionSource("human", "h1"))
    result = log.log_action(incident_id, ActionType.TEAM_DEPLOYED,
                             source=ActionSource("agent", "a1"), reference="DEPLOY-1")
    assert result["action_type"] == ActionType.TEAM_DEPLOYED.value


# ---------------------------------------------------------------------------
# add_victim
# ---------------------------------------------------------------------------

def test_add_victim_happy_path():
    incident_id = setup_incident()
    victim_id = log.add_victim(
        incident_id, description="adult male", location_description="basement",
        triage_category="immediate", source=ActionSource("agent", "a1"),
    )
    rec = log.get_incident(incident_id)
    assert any(v["victim_id"] == victim_id for v in rec["victims"])
    action_types = [a["action_type"] for a in rec["actions"]]
    assert ActionType.VICTIM_LOCATED.value in action_types


# ---------------------------------------------------------------------------
# raise_escalation + resolve_escalation
# ---------------------------------------------------------------------------

def test_raise_and_resolve_escalation_happy_path():
    incident_id = setup_incident()
    escalation_id = log.raise_escalation(
        incident_id, raised_by="a1", escalate_to="Incident Commander",
        reason="need backup", action_required="dispatch additional team",
    )
    rec = log.get_incident(incident_id)
    assert rec["open_escalations"] == 1
    log.resolve_escalation(escalation_id, resolved_by="h1")
    rec = log.get_incident(incident_id)
    assert rec["open_escalations"] == 0
    resolved = next(e for e in rec["escalations"] if e["escalation_id"] == escalation_id)
    assert resolved["resolved"] is True


# ---------------------------------------------------------------------------
# draft_plan / approve_plan
# ---------------------------------------------------------------------------

def test_draft_plan_always_status_draft():
    incident_id = setup_incident()
    plan_id = log.draft_plan(
        incident_id, drafted_by="planning-agent",
        objectives=["extract victims"], team_assignments={}, resource_assignments={},
        assumptions=["structure stable enough to enter"], open_questions=[],
    )
    rec = log.get_incident(incident_id)
    plan = next(p for p in rec["operational_plans"] if p["plan_id"] == plan_id)
    assert plan["status"] == "draft"


def test_approve_plan_rejects_non_human_succeeds_for_human():
    incident_id = setup_incident()
    plan_id = log.draft_plan(
        incident_id, drafted_by="planning-agent",
        objectives=["extract victims"], team_assignments={}, resource_assignments={},
        assumptions=[], open_questions=[],
    )
    try:
        log.approve_plan(plan_id, incident_id, approved_by=ActionSource("agent", "sneaky"))
        assert False, "should have raised UnauthorizedSourceError"
    except UnauthorizedSourceError:
        pass

    log.approve_plan(plan_id, incident_id, approved_by=ActionSource("human", "h1"))
    rec = log.get_incident(incident_id)
    plan = next(p for p in rec["operational_plans"] if p["plan_id"] == plan_id)
    assert plan["status"] == "approved"
    assert plan["approved_by"] == "h1"


# ---------------------------------------------------------------------------
# get_incident unknown id
# ---------------------------------------------------------------------------

def test_get_incident_unknown_id_raises():
    log.init_db(reset=True)
    try:
        log.get_incident("does-not-exist")
        assert False, "should have raised UnknownIncidentError"
    except UnknownIncidentError:
        pass


# ---------------------------------------------------------------------------
# MissingReferenceError — read the source: _log_action_conn() raises this
# whenever `reference` is falsy (empty string), regardless of action_type
# or source. This is enforced inside log_action (and any of the helper
# functions that write actions, e.g. open_hazard/add_victim/draft_plan).
# ---------------------------------------------------------------------------

def test_log_action_empty_reference_raises_missing_reference_error():
    incident_id = setup_incident()
    try:
        log.log_action(
            incident_id, ActionType.SITUATION_REPORT,
            source=ActionSource("agent", "a1"), reference="",
        )
        assert False, "should have raised MissingReferenceError"
    except MissingReferenceError:
        pass


# ---------------------------------------------------------------------------
# CORRECTION never overwrites
# ---------------------------------------------------------------------------

def test_correction_never_overwrites_original():
    incident_id = setup_incident()
    original = log.log_action(
        incident_id, ActionType.SITUATION_REPORT,
        source=ActionSource("agent", "a1"), reference="SR-1",
    )
    log.log_action(
        incident_id, ActionType.CORRECTION,
        source=ActionSource("human", "h1"), reference="SR-1-FIXED",
        corrects_action_id=original["action_id"],
    )
    rec = log.get_incident(incident_id)
    action_types = [a["action_type"] for a in rec["actions"]]
    assert action_types.count(ActionType.SITUATION_REPORT.value) == 1
    assert action_types.count(ActionType.CORRECTION.value) == 1
    original_action = next(a for a in rec["actions"] if a["action_id"] == original["action_id"])
    assert original_action["reference"] == "SR-1"  # untouched


ALL_TESTS = [
    test_open_incident_happy_path,
    test_log_action_happy_path_agent_non_human_only,
    test_log_action_agent_cannot_approve_plan,
    test_log_action_agent_cannot_clear_hazard,
    test_log_action_agent_cannot_close_incident,
    test_log_action_all_human_only_types_reject_agent_source,
    test_open_hazard_happy_path,
    test_clear_hazard_by_agent_rejected_by_human_succeeds,
    test_hazard_block_prevents_team_deployed,
    test_hazard_block_does_not_prevent_unrelated_action,
    test_hazard_block_cleared_once_hazard_resolved,
    test_add_victim_happy_path,
    test_raise_and_resolve_escalation_happy_path,
    test_draft_plan_always_status_draft,
    test_approve_plan_rejects_non_human_succeeds_for_human,
    test_get_incident_unknown_id_raises,
    test_log_action_empty_reference_raises_missing_reference_error,
    test_correction_never_overwrites_original,
]


if __name__ == "__main__":
    passed, failed = 0, 0
    for t in ALL_TESTS:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
