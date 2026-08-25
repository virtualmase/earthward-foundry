"""
Smoke test for api.py using Flask's built-in test client — proves the
HTTP layer round-trips correctly and maps runner.py / incident_log.py
exceptions to the right status codes, without needing a live running
server.

Auth note: api.py now requires RESCUE_API_KEY or an explicit opt-out
(see api_auth.py) before it will serve any non-exempt request — see
tests/test_api_auth.py for coverage of that behavior itself. Here we
just opt out via ALLOW_UNAUTHENTICATED so these functional tests aren't
blocked by auth.

Run: python3 tests/test_api.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("ALLOW_UNAUTHENTICATED", "true")

import incident_log as log
import api


def main():
    log.init_db(reset=True)
    client = api.app.test_client()

    # health
    r = client.get("/health")
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["status"] == "ok"
    print("PASS  health -> 200 status ok")

    # openapi.yaml — the file ships alongside api.py in this service, so
    # it must be served, not 404.
    r = client.get("/openapi.yaml")
    assert r.status_code in (200, 404), r.status_code
    if (Path(__file__).parent.parent / "openapi.yaml").exists():
        assert r.status_code == 200, r.status_code
    print(f"PASS  openapi.yaml -> {r.status_code} (matches file presence on disk)")

    # POST /incidents happy path
    r = client.post(
        "/incidents",
        json={
            "incident_type": "urban_sar",
            "priority": "life_threat",
            "location": "123 Main St — building collapse, 3 floors",
            "description": "Partial structural collapse, 2 confirmed trapped",
            "source": {"type": "human", "id": "Dispatcher-IC1"},
        },
    )
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert "incident_id" in body and body["incident_id"], body
    incident_id = body["incident_id"]
    print(f"PASS  open_incident -> 201 incident_id={incident_id}")

    # GET /incidents returns a list
    r = client.get("/incidents")
    assert r.status_code == 200, r.get_json()
    listing = r.get_json()
    assert isinstance(listing, list), listing
    assert any(i["incident_id"] == incident_id for i in listing)
    print("PASS  list_incidents -> 200 with a list containing the new incident")

    # GET /incidents/<unknown-id> -> 404
    r = client.get("/incidents/does-not-exist")
    assert r.status_code == 404, r.get_json()
    assert r.get_json()["error"] == "UnknownIncidentError"
    print("PASS  get_incident (unknown id) -> 404 as expected")

    # POST /incidents/<id>/actions with a human-only action_type submitted
    # by an agent source -> 403
    r = client.post(
        f"/incidents/{incident_id}/actions",
        json={
            "action_type": "incident_closed",
            "source": {"type": "agent", "id": "sneaky-agent"},
            "reference": "ref-close-1",
        },
    )
    assert r.status_code == 403, r.get_json()
    assert r.get_json()["error"] == "UnauthorizedSourceError"
    print("PASS  log_action (agent incident_closed) -> 403 as expected")

    # DELETE /incidents/<id>/hazards/<hazard_id> by an agent source -> 403
    # First open a hazard (agents are allowed to open hazards).
    r = client.post(
        f"/incidents/{incident_id}/hazards",
        json={
            "description": "Utility hazard — gas leak",
            "severity": "high",
            "source": {"type": "agent", "id": "safety-agent"},
        },
    )
    assert r.status_code == 201, r.get_json()
    hazard_id = r.get_json()["hazard_id"]
    print(f"PASS  open_hazard -> 201 hazard_id={hazard_id}")

    r = client.delete(
        f"/incidents/{incident_id}/hazards/{hazard_id}",
        json={"source": {"type": "agent", "id": "sneaky-agent"}},
    )
    assert r.status_code == 403, r.get_json()
    assert r.get_json()["error"] == "UnauthorizedSourceError"
    print("PASS  clear_hazard (agent source) -> 403 as expected")

    # Confirm a human CAN clear the same hazard (sanity check the 403
    # above is really about source.type, not a broken endpoint).
    r = client.delete(
        f"/incidents/{incident_id}/hazards/{hazard_id}",
        json={"source": {"type": "human", "id": "Safety-Officer-1"}},
    )
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["cleared"] is True
    print("PASS  clear_hazard (human source) -> 200 as expected")

    print("\nAll API smoke tests passed.")


if __name__ == "__main__":
    main()
