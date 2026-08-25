"""
Regression tests for the Quality Engineering agent logic (quality.py).
Run: python3 tests/test_quality.py  (or python3 -m pytest tests/)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "traceability"))

import service as trace  # noqa: E402
import quality  # noqa: E402


def setup_part():
    trace.init_db(reset=True)
    return trace.create_part(part_number="EW-QA-TEST", revision="A")


def test_open_ncr_writes_traceability_event():
    part_id = setup_part()
    result = quality.open_ncr(part_id, "NCR-1", "bore-dia", "tool wear")
    assert result["event_type"] == "ncr_opened"
    record = trace.get_record(part_id)
    assert record["current_status"] in ("ncr_open", "acceptance_blocked")


def test_open_ncr_never_closes_or_waives_itself():
    """quality.py exposes no close/waive function at all — the module
    doesn't even attempt human-only events; the traceability layer would
    reject it regardless."""
    assert not hasattr(quality, "close_ncr")
    assert not hasattr(quality, "waive_ncr")


def test_acceptance_status_clear_with_no_ncrs():
    part_id = setup_part()
    status = quality.acceptance_status(part_id)
    assert status["status"] == "CLEAR"
    assert status["open_ncrs"] == []
    assert status["waiting_on"] is None


def test_acceptance_status_blocked_with_open_ncr():
    part_id = setup_part()
    quality.open_ncr(part_id, "NCR-2", "length", "fixture drift")
    status = quality.acceptance_status(part_id)
    assert status["status"] == "BLOCKED"
    assert len(status["open_ncrs"]) == 1
    assert status["open_ncrs"][0]["reference"] == "NCR-2"
    assert status["waiting_on"] is not None
    assert "NCR-2" in status["waiting_on"]


def test_acceptance_status_clear_after_human_closes_ncr():
    part_id = setup_part()
    quality.open_ncr(part_id, "NCR-3", "length", "fixture drift")
    # Only a human can close an NCR — enforced by the traceability layer,
    # not by quality.py itself.
    trace.append_event(part_id, "ncr_closed", source=trace.Source("human", "h1"), reference="NCR-3")
    status = quality.acceptance_status(part_id)
    assert status["status"] == "CLEAR"


def test_acceptance_status_agent_cannot_close_ncr():
    part_id = setup_part()
    quality.open_ncr(part_id, "NCR-4", "length", "fixture drift")
    try:
        trace.append_event(part_id, "ncr_closed", source=trace.Source("agent", "a1"), reference="NCR-4")
        assert False, "should have raised UnauthorizedSourceError"
    except trace.UnauthorizedSourceError:
        pass
    status = quality.acceptance_status(part_id)
    assert status["status"] == "BLOCKED"


def test_correlate_root_cause_flags_systemic_pattern_at_three():
    trace.init_db(reset=True)
    part_ids = [trace.create_part(part_number=f"EW-QA-{i}", revision="A") for i in range(3)]
    for pid in part_ids:
        quality.open_ncr(pid, f"NCR-{pid}", "bore-dia", "tool wear")
    result = quality.correlate_root_cause(part_ids)
    assert "tool wear" in result["systemic_patterns"]
    assert set(result["systemic_patterns"]["tool wear"]) == set(part_ids)


def test_correlate_root_cause_below_threshold_not_systemic():
    trace.init_db(reset=True)
    part_ids = [trace.create_part(part_number=f"EW-QA2-{i}", revision="A") for i in range(2)]
    for pid in part_ids:
        quality.open_ncr(pid, f"NCR-{pid}", "bore-dia", "tool wear")
    result = quality.correlate_root_cause(part_ids)
    assert "tool wear" in result["all_causes"]
    assert "tool wear" not in result["systemic_patterns"]


def test_correlate_root_cause_defaults_unspecified_when_no_hypothesis():
    part_id = setup_part()
    trace.append_event(part_id, "ncr_opened", source=trace.Source("agent", "a1"), reference="NCR-X")
    result = quality.correlate_root_cause([part_id])
    assert "unspecified" in result["all_causes"]


ALL_TESTS = [
    test_open_ncr_writes_traceability_event,
    test_open_ncr_never_closes_or_waives_itself,
    test_acceptance_status_clear_with_no_ncrs,
    test_acceptance_status_blocked_with_open_ncr,
    test_acceptance_status_clear_after_human_closes_ncr,
    test_acceptance_status_agent_cannot_close_ncr,
    test_correlate_root_cause_flags_systemic_pattern_at_three,
    test_correlate_root_cause_below_threshold_not_systemic,
    test_correlate_root_cause_defaults_unspecified_when_no_hypothesis,
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
