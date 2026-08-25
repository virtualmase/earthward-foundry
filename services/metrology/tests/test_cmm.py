"""
Regression tests for the CMM Programming agent logic (cmm.py).
Run: python3 tests/test_cmm.py  (or python3 -m pytest tests/)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "traceability"))

import service as trace  # noqa: E402
import cmm  # noqa: E402


def setup_part():
    trace.init_db(reset=True)
    return trace.create_part(part_number="EW-CMM-TEST", revision="A")


def test_evaluate_feature_pass_within_band():
    # nominal=10, tolerance=1 -> band [9, 11], margin zone = 0.2 * 0.10 = 0.02
    assert cmm.evaluate_feature(measured=10.0, nominal=10.0, tolerance=1.0) == "PASS"


def test_evaluate_feature_marginal_near_upper_limit():
    # upper limit is 11; within 10% of the 2.0-wide band (0.2) of the limit -> MARGINAL
    assert cmm.evaluate_feature(measured=10.85, nominal=10.0, tolerance=1.0) == "MARGINAL"


def test_evaluate_feature_marginal_near_lower_limit():
    assert cmm.evaluate_feature(measured=9.15, nominal=10.0, tolerance=1.0) == "MARGINAL"


def test_evaluate_feature_fail_outside_band():
    assert cmm.evaluate_feature(measured=12.0, nominal=10.0, tolerance=1.0) == "FAIL"
    assert cmm.evaluate_feature(measured=8.0, nominal=10.0, tolerance=1.0) == "FAIL"


def test_run_inspection_all_pass_overall_pass():
    part_id = setup_part()
    result = cmm.run_inspection(
        part_id, "PROG-1",
        features=[
            {"name": "bore-dia", "nominal": 10.0, "tolerance": 1.0, "measured": 10.0},
            {"name": "length", "nominal": 50.0, "tolerance": 2.0, "measured": 50.5},
        ],
    )
    assert result["overall"] == "PASS"
    assert len(result["features"]) == 2
    assert all(f["result"] == "PASS" for f in result["features"])


def test_run_inspection_any_fail_overall_fail():
    part_id = setup_part()
    result = cmm.run_inspection(
        part_id, "PROG-2",
        features=[
            {"name": "bore-dia", "nominal": 10.0, "tolerance": 1.0, "measured": 10.0},
            {"name": "length", "nominal": 50.0, "tolerance": 2.0, "measured": 60.0},
        ],
    )
    assert result["overall"] == "FAIL"


def test_run_inspection_marginal_without_fail_overall_marginal():
    part_id = setup_part()
    result = cmm.run_inspection(
        part_id, "PROG-3",
        features=[
            {"name": "bore-dia", "nominal": 10.0, "tolerance": 1.0, "measured": 10.85},
        ],
    )
    assert result["overall"] == "MARGINAL"


def test_run_inspection_never_softens_fail_and_writes_traceability_events():
    """The agent must never adjust a measurement to force a PASS, and the
    inspection_result event it writes must be visible in the real
    traceability record, not just in the returned dict."""
    part_id = setup_part()
    cmm.run_inspection(
        part_id, "PROG-4",
        features=[{"name": "bore-dia", "nominal": 10.0, "tolerance": 1.0, "measured": 99.0}],
    )
    record = trace.get_record(part_id)
    event_types = [e["event_type"] for e in record["events"]]
    assert "inspection_program_run" in event_types
    assert "inspection_result" in event_types
    result_event = next(e for e in record["events"] if e["event_type"] == "inspection_result")
    assert result_event["data"]["overall"] == "FAIL"
    assert result_event["source"]["type"] == "agent"
    assert result_event["source"]["id"] == cmm.CMM_AGENT_ID


def test_run_inspection_writes_program_run_before_result():
    """Sequencing: the traceability service rejects inspection_result before
    inspection_program_run exists, so run_inspection must write them in
    that order (proves cmm.py can't skip the required precondition)."""
    part_id = setup_part()
    cmm.run_inspection(
        part_id, "PROG-5",
        features=[{"name": "length", "nominal": 50.0, "tolerance": 2.0, "measured": 50.0}],
    )
    record = trace.get_record(part_id)
    event_types = [e["event_type"] for e in record["events"]]
    assert event_types.index("inspection_program_run") < event_types.index("inspection_result")


ALL_TESTS = [
    test_evaluate_feature_pass_within_band,
    test_evaluate_feature_marginal_near_upper_limit,
    test_evaluate_feature_marginal_near_lower_limit,
    test_evaluate_feature_fail_outside_band,
    test_run_inspection_all_pass_overall_pass,
    test_run_inspection_any_fail_overall_fail,
    test_run_inspection_marginal_without_fail_overall_marginal,
    test_run_inspection_never_softens_fail_and_writes_traceability_events,
    test_run_inspection_writes_program_run_before_result,
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
