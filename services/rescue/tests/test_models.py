"""
Regression tests for the Rescue service's data models (models.py).
Run: python3 tests/test_models.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import (
    ActionSource,
    ActionType,
    Escalation,
    Hazard,
    Incident,
    IncidentAction,
    IncidentPriority,
    IncidentStatus,
    IncidentType,
    Victim,
    now_iso,
)


def _make_incident(**overrides) -> Incident:
    defaults = dict(
        incident_id="INC-1",
        incident_type=IncidentType.URBAN_SAR,
        priority=IncidentPriority.LIFE_THREAT,
        location="123 Main St",
        reported_at=now_iso(),
        reported_by=ActionSource("human", "h1"),
        description="structural collapse",
    )
    defaults.update(overrides)
    return Incident(**defaults)


def _action(action_type: ActionType, source: ActionSource = None, **overrides) -> IncidentAction:
    defaults = dict(
        action_id=f"act-{action_type.value}",
        incident_id="INC-1",
        timestamp=now_iso(),
        action_type=action_type,
        source=source or ActionSource("agent", "a1"),
        reference=f"ref-{action_type.value}",
    )
    defaults.update(overrides)
    return IncidentAction(**defaults)


def _hazard(severity="critical", cleared_at=None, **overrides) -> Hazard:
    defaults = dict(
        hazard_id="HZ-1",
        description="gas leak",
        severity=severity,
        opened_at=now_iso(),
        opened_by=ActionSource("agent", "a1"),
        cleared_at=cleared_at,
    )
    defaults.update(overrides)
    return Hazard(**defaults)


# ---------------------------------------------------------------------------
# ActionSource
# ---------------------------------------------------------------------------

def test_action_source_rejects_invalid_type():
    try:
        ActionSource(type="robot", id="a1")
        assert False, "should have raised ValueError for invalid source.type"
    except ValueError:
        pass


def test_action_source_is_human():
    human = ActionSource(type="human", id="h1")
    agent = ActionSource(type="agent", id="a1")
    assert human.is_human() is True
    assert agent.is_human() is False


# ---------------------------------------------------------------------------
# Incident.current_status derivation
# ---------------------------------------------------------------------------

def test_current_status_reported_with_no_actions():
    inc = _make_incident(actions=[])
    assert inc.current_status == IncidentStatus.REPORTED


def test_current_status_assessing_after_situation_report():
    inc = _make_incident(actions=[_action(ActionType.SITUATION_REPORT)])
    assert inc.current_status == IncidentStatus.ASSESSING


def test_current_status_planning_after_plan_approved():
    inc = _make_incident(actions=[
        _action(ActionType.SITUATION_REPORT),
        _action(ActionType.OPERATIONAL_PLAN_DRAFTED),
        _action(ActionType.OPERATIONAL_PLAN_APPROVED, source=ActionSource("human", "h1")),
    ])
    assert inc.current_status == IncidentStatus.PLANNING


def test_current_status_operations_after_team_deployed():
    inc = _make_incident(actions=[
        _action(ActionType.SITUATION_REPORT),
        _action(ActionType.OPERATIONAL_PLAN_APPROVED, source=ActionSource("human", "h1")),
        _action(ActionType.TEAM_DEPLOYED),
    ])
    assert inc.current_status == IncidentStatus.OPERATIONS


def test_current_status_hazard_blocked_with_open_critical_hazard():
    inc = _make_incident(
        actions=[
            _action(ActionType.SITUATION_REPORT),
            _action(ActionType.OPERATIONAL_PLAN_APPROVED, source=ActionSource("human", "h1")),
            _action(ActionType.TEAM_DEPLOYED),
        ],
        hazards=[_hazard(severity="critical", cleared_at=None)],
    )
    assert inc.current_status == IncidentStatus.HAZARD_BLOCKED


def test_current_status_hazard_blocked_ignores_low_severity_or_cleared():
    # Low severity open hazard does not block.
    inc = _make_incident(
        actions=[_action(ActionType.TEAM_DEPLOYED)],
        hazards=[_hazard(severity="low", cleared_at=None)],
    )
    assert inc.current_status == IncidentStatus.OPERATIONS

    # High severity but cleared hazard does not block.
    inc2 = _make_incident(
        actions=[_action(ActionType.TEAM_DEPLOYED)],
        hazards=[_hazard(severity="high", cleared_at=now_iso())],
    )
    assert inc2.current_status == IncidentStatus.OPERATIONS


def test_current_status_extracting_after_extraction_started():
    inc = _make_incident(actions=[
        _action(ActionType.SITUATION_REPORT),
        _action(ActionType.VICTIM_LOCATED),
        _action(ActionType.EXTRACTION_STARTED),
    ])
    assert inc.current_status == IncidentStatus.EXTRACTING


def test_current_status_transferring_after_victim_transferred():
    inc = _make_incident(actions=[
        _action(ActionType.SITUATION_REPORT),
        _action(ActionType.VICTIM_STABILIZED),
        _action(ActionType.VICTIM_TRANSFERRED, source=ActionSource("human", "h1")),
    ])
    assert inc.current_status == IncidentStatus.TRANSFERRING


def test_current_status_closed_after_incident_closed():
    inc = _make_incident(actions=[
        _action(ActionType.SITUATION_REPORT),
        _action(ActionType.INCIDENT_CLOSED, source=ActionSource("human", "h1")),
    ])
    assert inc.current_status == IncidentStatus.CLOSED


def test_current_status_closed_takes_priority_over_everything():
    """INCIDENT_CLOSED check comes first in models.py — even with an open
    critical hazard and victim transferred present, closed wins."""
    inc = _make_incident(
        actions=[
            _action(ActionType.VICTIM_TRANSFERRED, source=ActionSource("human", "h1")),
            _action(ActionType.INCIDENT_CLOSED, source=ActionSource("human", "h1")),
        ],
        hazards=[_hazard(severity="critical", cleared_at=None)],
    )
    assert inc.current_status == IncidentStatus.CLOSED


# ---------------------------------------------------------------------------
# Hazard.is_open
# ---------------------------------------------------------------------------

def test_hazard_is_open_property():
    open_hazard = _hazard(cleared_at=None)
    cleared_hazard = _hazard(cleared_at=now_iso())
    assert open_hazard.is_open is True
    assert cleared_hazard.is_open is False


# ---------------------------------------------------------------------------
# Incident helper properties
# ---------------------------------------------------------------------------

def test_open_hazards_property():
    h1 = _hazard(hazard_id="HZ-1", cleared_at=None)
    h2 = _hazard(hazard_id="HZ-2", cleared_at=now_iso())
    inc = _make_incident(hazards=[h1, h2])
    assert inc.open_hazards == [h1]


def test_open_escalations_property():
    e1 = Escalation(
        escalation_id="ESC-1", incident_id="INC-1", timestamp=now_iso(),
        raised_by="a1", escalate_to="Incident Commander", reason="need backup",
        action_required="dispatch team", resolved=False,
    )
    e2 = Escalation(
        escalation_id="ESC-2", incident_id="INC-1", timestamp=now_iso(),
        raised_by="a1", escalate_to="Safety Officer", reason="resolved issue",
        action_required="none", resolved=True,
    )
    inc = _make_incident(escalations=[e1, e2])
    assert inc.open_escalations == [e1]


def test_unextracted_victims_property():
    v1 = Victim(
        victim_id="V-1", description="adult male", location_description="basement",
        triage_category="immediate", extracted_at=None,
    )
    v2 = Victim(
        victim_id="V-2", description="adult female", location_description="attic",
        triage_category="delayed", extracted_at=now_iso(),
    )
    inc = _make_incident(victims=[v1, v2])
    assert inc.unextracted_victims == [v1]


ALL_TESTS = [
    test_action_source_rejects_invalid_type,
    test_action_source_is_human,
    test_current_status_reported_with_no_actions,
    test_current_status_assessing_after_situation_report,
    test_current_status_planning_after_plan_approved,
    test_current_status_operations_after_team_deployed,
    test_current_status_hazard_blocked_with_open_critical_hazard,
    test_current_status_hazard_blocked_ignores_low_severity_or_cleared,
    test_current_status_extracting_after_extraction_started,
    test_current_status_transferring_after_victim_transferred,
    test_current_status_closed_after_incident_closed,
    test_current_status_closed_takes_priority_over_everything,
    test_hazard_is_open_property,
    test_open_hazards_property,
    test_open_escalations_property,
    test_unextracted_victims_property,
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
