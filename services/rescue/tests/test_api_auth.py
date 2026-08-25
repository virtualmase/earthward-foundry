"""
Regression tests for api_auth.py's transport-layer authentication, as
wired into the rescue service's api.py.
Run: python3 tests/test_api_auth.py
"""
import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _fresh_client(env: dict):
    """Reload api.py under a controlled environment so each test gets an
    independent view of RESCUE_API_KEY / ALLOW_UNAUTHENTICATED."""
    for key in ("RESCUE_API_KEY", "ALLOW_UNAUTHENTICATED"):
        os.environ.pop(key, None)
    os.environ.update(env)

    import incident_log as log
    log.init_db(reset=True)

    for mod in ("api", "api_auth", "runner"):
        sys.modules.pop(mod, None)
    api = importlib.import_module("api")
    return api.app.test_client()


def test_unset_key_refuses_by_default():
    client = _fresh_client({})
    r = client.get("/incidents/does-not-exist")
    assert r.status_code == 500, r.get_json()
    assert r.get_json()["error"] == "ServerMisconfigured"


def test_unset_key_allows_when_explicitly_opted_out():
    client = _fresh_client({"ALLOW_UNAUTHENTICATED": "true"})
    r = client.get("/health")
    assert r.status_code == 200


def test_missing_bearer_token_rejected():
    client = _fresh_client({"RESCUE_API_KEY": "s3cret"})
    r = client.get("/incidents")
    assert r.status_code == 401, r.get_json()
    assert r.get_json()["error"] == "Unauthorized"


def test_wrong_bearer_token_rejected():
    client = _fresh_client({"RESCUE_API_KEY": "s3cret"})
    r = client.get("/incidents", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401, r.get_json()


def test_correct_bearer_token_accepted():
    client = _fresh_client({"RESCUE_API_KEY": "s3cret"})
    r = client.get("/incidents", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200, r.get_json()


def test_health_and_openapi_exempt_even_without_key():
    client = _fresh_client({"RESCUE_API_KEY": "s3cret"})
    r = client.get("/health")
    assert r.status_code == 200
    r = client.get("/openapi.yaml")
    assert r.status_code in (200, 404)  # exempt from auth either way


ALL_TESTS = [
    test_unset_key_refuses_by_default,
    test_unset_key_allows_when_explicitly_opted_out,
    test_missing_bearer_token_rejected,
    test_wrong_bearer_token_rejected,
    test_correct_bearer_token_accepted,
    test_health_and_openapi_exempt_even_without_key,
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
