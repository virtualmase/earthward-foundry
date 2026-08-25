"""
Smoke test for api.py using Flask's built-in test client — proves the
HTTP layer round-trips correctly and maps service.py exceptions to the
right status codes, without needing a live running server.

Run: python3 tests/test_api.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# The API now requires TRACEABILITY_API_KEY or explicit opt-out for
# unauthenticated access (see api_auth.py) — tests exercise the app
# directly via Flask's test client, so opt out of auth rather than
# faking a key.
os.environ.setdefault("ALLOW_UNAUTHENTICATED", "true")

import service as svc
import api


def main():
    svc.init_db(reset=True)
    client = api.app.test_client()

    # health
    r = client.get("/health")
    assert r.status_code == 200, r.get_json()

    # create part
    r = client.post("/parts", json={"part_number": "EW-API-TEST-001", "revision": "A"})
    assert r.status_code == 201, r.get_json()
    part_id = r.get_json()["part_id"]
    print(f"PASS  create_part -> {part_id}")

    # append a legal event
    r = client.post(
        f"/parts/{part_id}/events",
        json={
            "event_type": "material_receipt",
            "source": {"type": "agent", "id": "materials-engineer-agent"},
            "reference": "CERT-9001",
        },
    )
    assert r.status_code == 201, r.get_json()
    print("PASS  append_event (legal, agent-sourced)")

    # illegal: agent tries acceptance_decision -> expect 403
    r = client.post(
        f"/parts/{part_id}/events",
        json={
            "event_type": "acceptance_decision",
            "source": {"type": "agent", "id": "sneaky-agent"},
            "reference": "ACPT-X",
        },
    )
    assert r.status_code == 403, r.get_json()
    print("PASS  append_event (agent acceptance_decision) -> 403 as expected")

    # unknown part -> 404
    r = client.get("/parts/does-not-exist")
    assert r.status_code == 404, r.get_json()
    print("PASS  get_record (unknown part) -> 404 as expected")

    # get_record round-trip
    r = client.get(f"/parts/{part_id}")
    assert r.status_code == 200
    body = r.get_json()
    assert body["current_status"] == "material_received"
    assert len(body["events"]) == 1
    print("PASS  get_record round-trip matches what was written")

    print("\nAll API smoke tests passed.")


if __name__ == "__main__":
    main()
