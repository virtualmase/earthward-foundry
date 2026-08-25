"""Regression coverage for the installable live Claude agent module.

Run: python3 tests/test_live_agent_import.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_live_agent_imports_with_declared_dependencies():
    import live_agent

    assert live_agent.RescueAgent.__name__ == "RescueAgent"


ALL_TESTS = [
    test_live_agent_imports_with_declared_dependencies,
]


if __name__ == "__main__":
    passed, failed = 0, 0
    for test in ALL_TESTS:
        try:
            test()
            print(f"PASS  {test.__name__}")
            passed += 1
        except AssertionError as exc:
            print(f"FAIL  {test.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            print(f"ERROR {test.__name__}: {type(exc).__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
