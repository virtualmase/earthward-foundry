"""
Regression tests for runner.py's TaskForceRunner — the rescue pipeline
orchestrator that routes an incident through the agent fleet in phase
order and enforces human-approval gates before proceeding.

Run: python3 tests/test_runner.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# runner.py imports api-adjacent modules that don't touch api_auth.py
# directly, but keep behavior consistent with the rest of the test suite
# in case any future import chain pulls in api.py.
os.environ.setdefault("ALLOW_UNAUTHENTICATED", "true")

import incident_log as log
from models import ActionSource, IncidentType, IncidentPriority, RescueError, UnauthorizedSourceError, UnknownIncidentError
from runner import TaskForceRunner


def _open_incident(runner, incident_type=IncidentType.URBAN_SAR, priority=IncidentPriority.LIFE_THREAT):
    return runner.intake(
        incident_type=incident_type,
        priority=priority,
        location="123 Main St — building collapse, 3 floors",
        description="Partial structural collapse, 2 confirmed trapped, gas leak reported",
        reported_by=ActionSource(type="human", id="Dispatcher-IC1"),
    )


def setup_runner():
    log.init_db(reset=True)
    return TaskForceRunner()


# ---------------------------------------------------------------------------
# intake() happy path
# ---------------------------------------------------------------------------

def test_intake_happy_path_returns_incident_id_and_reaches_plan_draft():
    """
    intake() should run phase 1 (incident log, implicit), then phases 2-5
    (safety, assessment, resource, planning) and halt there — planning
    always sets halt=True to force a human gate before operations-agent
    even runs. So phases_completed should be exactly those 4 agent names,
    current_phase should be planning-agent, and awaiting_human should be
    None (the halt happens via the phase's own "halt" flag, not via the
    _check_human_gate check for operations-agent, since the pipeline never
    reaches that phase).
    """
    runner = setup_runner()
    result = _open_incident(runner)

    assert "incident_id" in result and result["incident_id"], result
    assert result["phases_completed"] == [
        "safety-agent",
        "assessment-agent",
        "resource-agent",
        "planning-agent",
    ], result["phases_completed"]
    assert result["current_phase"] == "planning-agent", result["current_phase"]
    assert result["awaiting_human"] is None, result["awaiting_human"]
    assert len(result["blocks"]) == 1, result["blocks"]
    assert result["blocks"][0]["phase"] == "planning-agent"
    assert "approval" in result["blocks"][0]["reason"].lower()

    # Planning output should be present with a plan_id and draft status note.
    planning_output = result["outputs"]["planning-agent"]
    assert planning_output["status"] == "plan_drafted"
    assert "plan_id" in planning_output and planning_output["plan_id"]
    assert planning_output["halt"] is True

    # Sanity: the incident really was opened and is readable via the log.
    record = log.get_incident(result["incident_id"])
    assert record["incident_id"] == result["incident_id"]


def test_intake_raises_escalations_along_the_way():
    """Safety, assessment, resource, and planning phases all raise named
    escalations for this incident type/priority — confirm they surface."""
    runner = setup_runner()
    result = _open_incident(runner)
    escalate_targets = {e["escalate_to"] for e in result["escalations"]}
    assert "Safety Officer" in escalate_targets
    assert "Incident Commander" in escalate_targets


# ---------------------------------------------------------------------------
# resume() — resuming after a human gate is cleared
# ---------------------------------------------------------------------------

def test_resume_without_approval_reports_awaiting_human():
    """Attempting to resume into operations-agent before the plan has been
    approved must not proceed — it should surface awaiting_human with the
    operations-agent gate message, and phases_completed must stay empty."""
    runner = setup_runner()
    intake_result = _open_incident(runner)
    incident_id = intake_result["incident_id"]

    result = runner.resume(
        incident_id=incident_id,
        from_phase="operations-agent",
        authorized_by=ActionSource(type="human", id="IC-1"),
    )
    assert result["phases_completed"] == [], result["phases_completed"]
    assert result["awaiting_human"] is not None
    assert result["awaiting_human"]["phase"] == "operations-agent"
    assert "approved operational plan" in result["awaiting_human"]["message"]
    assert result["blocks"] == []


def test_resume_after_plan_approval_proceeds_past_operations_gate():
    """Once a human approves the drafted plan (via the log layer, mirroring
    what the API's /plans/<id>/approve endpoint would do), resume() from
    operations-agent should run operations-agent and integration-agent,
    then halt again at verification-agent's own human gate (extraction
    complete not yet logged)."""
    runner = setup_runner()
    intake_result = _open_incident(runner)
    incident_id = intake_result["incident_id"]

    record = log.get_incident(incident_id)
    plan = record["operational_plans"][-1]
    log.approve_plan(
        plan_id=plan["plan_id"],
        incident_id=incident_id,
        approved_by=ActionSource(type="human", id="IC-1"),
    )

    result = runner.resume(
        incident_id=incident_id,
        from_phase="operations-agent",
        authorized_by=ActionSource(type="human", id="IC-1"),
    )
    assert result["phases_completed"] == ["operations-agent", "integration-agent"], result["phases_completed"]
    assert result["current_phase"] == "verification-agent"
    assert result["awaiting_human"] is not None
    assert result["awaiting_human"]["phase"] == "verification-agent"
    assert "extraction complete" in result["awaiting_human"]["message"].lower()


def test_resume_requires_human_source():
    """resume() must reject a non-human authorized_by outright — this is
    checked up front, before any phase logic runs."""
    runner = setup_runner()
    intake_result = _open_incident(runner)
    incident_id = intake_result["incident_id"]

    try:
        runner.resume(
            incident_id=incident_id,
            from_phase="operations-agent",
            authorized_by=ActionSource(type="agent", id="sneaky-agent"),
        )
        assert False, "should have raised UnauthorizedSourceError"
    except UnauthorizedSourceError:
        pass


# ---------------------------------------------------------------------------
# _check_human_gate — confirm exactly what gates what
# ---------------------------------------------------------------------------

def test_check_human_gate_operations_requires_approved_plan():
    """Directly exercise _check_human_gate: operations-agent is gated on
    ActionType.OPERATIONAL_PLAN_APPROVED having been logged. Before
    approval it must return (False, <message>); after approval, (True, "")."""
    runner = setup_runner()
    intake_result = _open_incident(runner)
    incident_id = intake_result["incident_id"]

    cleared, message = runner._check_human_gate("operations-agent", incident_id)
    assert cleared is False
    assert "approved operational plan" in message

    record = log.get_incident(incident_id)
    plan = record["operational_plans"][-1]
    log.approve_plan(
        plan_id=plan["plan_id"],
        incident_id=incident_id,
        approved_by=ActionSource(type="human", id="IC-1"),
    )

    cleared, message = runner._check_human_gate("operations-agent", incident_id)
    assert cleared is True
    assert message == ""


def test_check_human_gate_verification_requires_extraction_complete():
    """verification-agent's gate is independent of operations-agent's —
    it checks for ActionType.EXTRACTION_COMPLETE, not plan approval."""
    runner = setup_runner()
    intake_result = _open_incident(runner)
    incident_id = intake_result["incident_id"]

    cleared, message = runner._check_human_gate("verification-agent", incident_id)
    assert cleared is False
    assert "extraction complete" in message.lower()


def test_operations_phase_without_gate_check_raises_invalid_sequence():
    """If _run_operations is invoked directly against an incident with no
    approved plan (bypassing the gate check the pipeline normally performs),
    it must raise InvalidSequenceError rather than silently proceeding or
    self-certifying — this is the exact configuration-error guard rail
    coded in _run_operations, not a generic rejection."""
    runner = setup_runner()
    intake_result = _open_incident(runner)
    incident_id = intake_result["incident_id"]

    try:
        runner._run_operations(incident_id, ActionSource(type="human", id="IC-1"))
        assert False, "should have raised InvalidSequenceError"
    except RescueError as e:
        # InvalidSequenceError is a subclass of RescueError; assert the
        # precise type per the source rather than just the base class.
        assert type(e).__name__ == "InvalidSequenceError", type(e)


# ---------------------------------------------------------------------------
# resume() with invalid phase name
# ---------------------------------------------------------------------------

def test_resume_unknown_phase_raises_rescue_error():
    """resume() looks up from_phase in the pipeline's phase name list and
    raises a plain RescueError (not UnknownIncidentError, not ValueError)
    when the name doesn't match any registered phase."""
    runner = setup_runner()
    intake_result = _open_incident(runner)
    incident_id = intake_result["incident_id"]

    try:
        runner.resume(
            incident_id=incident_id,
            from_phase="not-a-real-phase",
            authorized_by=ActionSource(type="human", id="IC-1"),
        )
        assert False, "should have raised RescueError for unknown phase"
    except RescueError as e:
        assert "Unknown phase" in str(e)


# ---------------------------------------------------------------------------
# UnknownIncidentError for an unknown incident_id
# ---------------------------------------------------------------------------

def test_resume_unknown_incident_is_caught_as_a_block_not_raised():
    """
    Naive expectation: resume() would raise UnknownIncidentError for a
    bogus incident_id. Actual behavior: resume()'s per-phase try/except
    catches (HazardBlockError, InvalidSequenceError, RescueError) — and
    UnknownIncidentError IS a RescueError subclass — so the very first
    phase handler's call to log.get_incident() raises UnknownIncidentError,
    which gets caught internally and appended to result["blocks"] instead
    of propagating. resume() itself never raises for an unknown incident.
    """
    runner = setup_runner()
    result = runner.resume(
        incident_id="does-not-exist",
        from_phase="safety-agent",
        authorized_by=ActionSource(type="human", id="IC-1"),
    )
    assert result["phases_completed"] == []
    assert len(result["blocks"]) == 1
    assert "No such incident_id" in result["blocks"][0]["reason"]


def test_check_human_gate_raises_unknown_incident_error_directly():
    """_check_human_gate() itself calls log.get_incident() with no
    surrounding try/except, so calling it directly (outside the pipeline's
    own exception handling) is where UnknownIncidentError actually
    propagates to the caller."""
    runner = setup_runner()
    try:
        runner._check_human_gate("operations-agent", "does-not-exist")
        assert False, "should have raised UnknownIncidentError"
    except UnknownIncidentError:
        pass


ALL_TESTS = [
    test_intake_happy_path_returns_incident_id_and_reaches_plan_draft,
    test_intake_raises_escalations_along_the_way,
    test_resume_without_approval_reports_awaiting_human,
    test_resume_after_plan_approval_proceeds_past_operations_gate,
    test_resume_requires_human_source,
    test_check_human_gate_operations_requires_approved_plan,
    test_check_human_gate_verification_requires_extraction_complete,
    test_operations_phase_without_gate_check_raises_invalid_sequence,
    test_resume_unknown_phase_raises_rescue_error,
    test_resume_unknown_incident_is_caught_as_a_block_not_raised,
    test_check_human_gate_raises_unknown_incident_error_directly,
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
