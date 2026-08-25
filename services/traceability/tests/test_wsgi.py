"""Regression coverage for the production WSGI entry point.

Run: python3 tests/test_wsgi.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_wsgi_initializes_traceability_ledger():
    with tempfile.TemporaryDirectory() as temp_dir:
        os.environ["TRACEABILITY_DB_PATH"] = str(Path(temp_dir) / "traceability.db")
        import wsgi

        assert wsgi.app.name == "api"
        assert Path(os.environ["TRACEABILITY_DB_PATH"]).exists()


ALL_TESTS = [
    test_wsgi_initializes_traceability_ledger,
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
