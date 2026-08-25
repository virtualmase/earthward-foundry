"""
Earthward Rescue Task Force — HTTP API.

Model-agnostic Flask wrapper over incident_log.py and runner.py.
Any LLM framework, human client, or integration tool can call this —
no Anthropic SDK, no Claude-specific tooling required.

Endpoints:
  POST   /incidents                       open a new incident (intake)
  GET    /incidents                       list all open incidents
  GET    /incidents/<id>                  get full incident record
  POST   /incidents/<id>/actions          log an action
  POST   /incidents/<id>/hazards          open a hazard
  DELETE /incidents/<id>/hazards/<hid>    clear a hazard (human-only)
  POST   /incidents/<id>/victims          add a victim
  POST   /incidents/<id>/escalations      raise an escalation
  PATCH  /escalations/<eid>/resolve       resolve an escalation
  POST   /incidents/<id>/plans            draft an operational plan
  PATCH  /incidents/<id>/plans/<pid>/approve  approve a plan (human-only)
  POST   /incidents/<id>/resume           resume pipeline from a named phase
  GET    /health                          liveness check
  GET    /openapi.yaml                    serve the OpenAPI spec

Run:
  pip install flask
  python api.py
  # -> http://127.0.0.1:5001

All rule enforcement stays in incident_log.py — this layer only
translates HTTP requests to function calls and maps exceptions to
HTTP status codes. Nothing is bypassed here.

Error shape (all 4xx/5xx):
  {"error": "<ExceptionClassName>", "message": "<detail>"}
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, request, send_file

import incident_log as log
from api_auth import require_api_key
from logging_config import configure_logging, logger
from models import (
    ActionSource,
    ActionType,
    IncidentPriority,
    IncidentType,
    HazardBlockError,
    InvalidSequenceError,
    MissingReferenceError,
    RescueError,
    UnauthorizedSourceError,
    UnknownIncidentError,
)
from runner import TaskForceRunner

app = Flask(__name__)
require_api_key(app, "RESCUE_API_KEY")
configure_logging(app, "rescue")
_runner = TaskForceRunner()
_OPENAPI_PATH = Path(__file__).parent / "openapi.yaml"


# ---------------------------------------------------------------------------
# Error helpers
# ---------------------------------------------------------------------------

def _err(exc: Exception, code: int):
    return jsonify({"error": type(exc).__name__, "message": str(exc)}), code


def _bad(msg: str):
    return jsonify({"error": "BadRequest", "message": msg}), 400


def _source(body: dict) -> ActionSource:
    """Parse source object from request body, raise 400 if malformed."""
    src = body.get("source")
    if not src or not isinstance(src, dict):
        raise ValueError("'source' object with 'type' and 'id' is required.")
    return ActionSource(type=src["type"], id=src["id"])


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

@app.post("/incidents")
def open_incident():
    """
    Open a new incident and run the pipeline through Phase 5 (plan draft).

    Body:
      incident_type  string  (urban_sar | wilderness_sar | disaster |
                               maritime | hazmat | medical_mass_cas)
      priority       string  (life_threat | urgent | standard | monitor)
      location       string
      description    string
      source         {type: "human"|"agent", id: string}
      incident_id    string  optional — supply to set a known ID

    Returns 201 with the pipeline result including incident_id.
    """
    body = request.get_json(force=True) or {}
    try:
        incident_type = IncidentType(body["incident_type"])
        priority = IncidentPriority(body["priority"])
        source = _source(body)
        result = _runner.intake(
            incident_type=incident_type,
            priority=priority,
            location=body["location"],
            description=body["description"],
            reported_by=source,
            incident_id=body.get("incident_id"),
        )
        return jsonify(result), 201
    except KeyError as e:
        return _bad(f"Missing required field: {e}")
    except ValueError as e:
        return _bad(str(e))
    except RescueError as e:
        return _err(e, 400)


@app.get("/incidents")
def list_incidents():
    """List all open (non-closed) incidents."""
    return jsonify(log.list_open_incidents())


@app.get("/incidents/<incident_id>")
def get_incident(incident_id: str):
    """Get the full record for an incident."""
    try:
        return jsonify(log.get_incident(incident_id))
    except UnknownIncidentError as e:
        return _err(e, 404)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

@app.post("/incidents/<incident_id>/actions")
def log_action(incident_id: str):
    """
    Append an action to an incident's log.

    Body:
      action_type         string  (see ActionType enum)
      source              {type, id}
      reference           string  — report ID, radio log ref, order number
      data                object  optional
      corrects_action_id  string  optional — for CORRECTION actions

    Human-only action_types (source.type must be "human"):
      operational_plan_approved, victim_transferred,
      hazard_mitigated, hazard_cleared, incident_closed
    """
    body = request.get_json(force=True) or {}
    try:
        action_type = ActionType(body["action_type"])
        source = _source(body)
        result = log.log_action(
            incident_id=incident_id,
            action_type=action_type,
            source=source,
            reference=body["reference"],
            data=body.get("data"),
            corrects_action_id=body.get("corrects_action_id"),
        )
        return jsonify(result), 201
    except UnknownIncidentError as e:
        return _err(e, 404)
    except UnauthorizedSourceError as e:
        return _err(e, 403)
    except (InvalidSequenceError, HazardBlockError) as e:
        return _err(e, 409)
    except (MissingReferenceError, RescueError) as e:
        return _err(e, 400)
    except KeyError as e:
        return _bad(f"Missing required field: {e}")
    except ValueError as e:
        return _bad(str(e))


# ---------------------------------------------------------------------------
# Hazards
# ---------------------------------------------------------------------------

@app.post("/incidents/<incident_id>/hazards")
def open_hazard(incident_id: str):
    """
    Log a new hazard against an incident.

    Body:
      description  string
      severity     string  (critical | high | moderate | low)
      source       {type, id}
      notes        string  optional
    """
    body = request.get_json(force=True) or {}
    try:
        source = _source(body)
        hazard_id = log.open_hazard(
            incident_id=incident_id,
            description=body["description"],
            severity=body["severity"],
            source=source,
            notes=body.get("notes", ""),
        )
        return jsonify({"hazard_id": hazard_id, "incident_id": incident_id}), 201
    except UnknownIncidentError as e:
        return _err(e, 404)
    except RescueError as e:
        return _err(e, 400)
    except KeyError as e:
        return _bad(f"Missing required field: {e}")
    except ValueError as e:
        return _bad(str(e))


@app.delete("/incidents/<incident_id>/hazards/<hazard_id>")
def clear_hazard(incident_id: str, hazard_id: str):
    """
    Clear a hazard — human-only.

    Body:
      source  {type: "human", id: string}
      notes   string  optional
    """
    body = request.get_json(force=True) or {}
    try:
        source = _source(body)
        log.clear_hazard(
            incident_id=incident_id,
            hazard_id=hazard_id,
            source=source,
            notes=body.get("notes", ""),
        )
        return jsonify({"cleared": True, "hazard_id": hazard_id}), 200
    except UnknownIncidentError as e:
        return _err(e, 404)
    except UnauthorizedSourceError as e:
        return _err(e, 403)
    except RescueError as e:
        return _err(e, 400)
    except (KeyError, ValueError) as e:
        return _bad(str(e))


# ---------------------------------------------------------------------------
# Victims
# ---------------------------------------------------------------------------

@app.post("/incidents/<incident_id>/victims")
def add_victim(incident_id: str):
    """
    Register a victim against an incident.

    Body:
      description           string
      location_description  string
      triage_category       string  (immediate | delayed | minimal | expectant)
      source                {type, id}
    """
    body = request.get_json(force=True) or {}
    try:
        source = _source(body)
        victim_id = log.add_victim(
            incident_id=incident_id,
            description=body["description"],
            location_description=body["location_description"],
            triage_category=body["triage_category"],
            source=source,
        )
        return jsonify({"victim_id": victim_id, "incident_id": incident_id}), 201
    except UnknownIncidentError as e:
        return _err(e, 404)
    except RescueError as e:
        return _err(e, 400)
    except KeyError as e:
        return _bad(f"Missing required field: {e}")
    except ValueError as e:
        return _bad(str(e))


# ---------------------------------------------------------------------------
# Escalations
# ---------------------------------------------------------------------------

@app.post("/incidents/<incident_id>/escalations")
def raise_escalation(incident_id: str):
    """
    Raise an escalation against an incident.

    Body:
      raised_by        string  — agent name or human ID
      escalate_to      string  — MUST be a named role/person, not "a human"
      reason           string
      action_required  string
    """
    body = request.get_json(force=True) or {}
    try:
        esc_id = log.raise_escalation(
            incident_id=incident_id,
            raised_by=body["raised_by"],
            escalate_to=body["escalate_to"],
            reason=body["reason"],
            action_required=body["action_required"],
        )
        return jsonify({"escalation_id": esc_id, "incident_id": incident_id}), 201
    except UnknownIncidentError as e:
        return _err(e, 404)
    except RescueError as e:
        return _err(e, 400)
    except KeyError as e:
        return _bad(f"Missing required field: {e}")


@app.patch("/escalations/<escalation_id>/resolve")
def resolve_escalation(escalation_id: str):
    """
    Mark an escalation resolved.

    Body:
      resolved_by  string  — named human
    """
    body = request.get_json(force=True) or {}
    try:
        log.resolve_escalation(
            escalation_id=escalation_id,
            resolved_by=body["resolved_by"],
        )
        return jsonify({"resolved": True, "escalation_id": escalation_id}), 200
    except RescueError as e:
        return _err(e, 400)
    except KeyError as e:
        return _bad(f"Missing required field: {e}")


# ---------------------------------------------------------------------------
# Operational plans
# ---------------------------------------------------------------------------

@app.post("/incidents/<incident_id>/plans")
def draft_plan(incident_id: str):
    """
    Draft an operational plan — always status='draft', never self-approved.

    Body:
      drafted_by            string
      objectives            [string]
      team_assignments      {team_id: objective}  optional
      resource_assignments  {resource_id: role}   optional
      assumptions           [string]
      open_questions        [string]
    """
    body = request.get_json(force=True) or {}
    try:
        plan_id = log.draft_plan(
            incident_id=incident_id,
            drafted_by=body["drafted_by"],
            objectives=body["objectives"],
            team_assignments=body.get("team_assignments", {}),
            resource_assignments=body.get("resource_assignments", {}),
            assumptions=body.get("assumptions", []),
            open_questions=body.get("open_questions", []),
        )
        return jsonify({"plan_id": plan_id, "status": "draft"}), 201
    except UnknownIncidentError as e:
        return _err(e, 404)
    except RescueError as e:
        return _err(e, 400)
    except KeyError as e:
        return _bad(f"Missing required field: {e}")


@app.patch("/incidents/<incident_id>/plans/<plan_id>/approve")
def approve_plan(incident_id: str, plan_id: str):
    """
    Approve an operational plan — human-only.

    Body:
      source  {type: "human", id: string}
    """
    body = request.get_json(force=True) or {}
    try:
        source = _source(body)
        log.approve_plan(
            plan_id=plan_id,
            incident_id=incident_id,
            approved_by=source,
        )
        return jsonify({"approved": True, "plan_id": plan_id}), 200
    except UnknownIncidentError as e:
        return _err(e, 404)
    except UnauthorizedSourceError as e:
        return _err(e, 403)
    except RescueError as e:
        return _err(e, 400)
    except (KeyError, ValueError) as e:
        return _bad(str(e))


# ---------------------------------------------------------------------------
# Pipeline resume
# ---------------------------------------------------------------------------

@app.post("/incidents/<incident_id>/resume")
def resume_pipeline(incident_id: str):
    """
    Resume the pipeline from a named phase after a human gate is cleared.

    Body:
      from_phase    string  — phase name (e.g. "operations-agent")
      source        {type: "human", id: string}

    Valid phase names:
      incident-log-agent, safety-agent, assessment-agent, resource-agent,
      planning-agent, operations-agent, integration-agent,
      verification-agent, command-agent
    """
    body = request.get_json(force=True) or {}
    try:
        source = _source(body)
        result = _runner.resume(
            incident_id=incident_id,
            from_phase=body["from_phase"],
            authorized_by=source,
        )
        return jsonify(result), 200
    except UnknownIncidentError as e:
        return _err(e, 404)
    except UnauthorizedSourceError as e:
        return _err(e, 403)
    except RescueError as e:
        return _err(e, 400)
    except KeyError as e:
        return _bad(f"Missing required field: {e}")
    except ValueError as e:
        return _bad(str(e))


# ---------------------------------------------------------------------------
# Spec + health
# ---------------------------------------------------------------------------

@app.get("/openapi.yaml")
def openapi_spec():
    """Serve the OpenAPI spec — any LLM or tool can fetch this to
    discover available endpoints and their schemas."""
    if _OPENAPI_PATH.exists():
        return send_file(_OPENAPI_PATH, mimetype="application/yaml")
    return jsonify({"error": "NotFound", "message": "openapi.yaml not found"}), 404


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "earthward-rescue-task-force"})


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.init_db(reset=False)
    port = int(os.environ.get("RESCUE_API_PORT", 5001))
    debug = os.environ.get("RESCUE_API_DEBUG", "false").lower() == "true"
    host = os.environ.get("RESCUE_API_HOST", "127.0.0.1")
    if debug and host not in ("127.0.0.1", "localhost"):
        raise SystemExit(
            "Refusing to start: RESCUE_API_DEBUG=true with a non-localhost "
            "RESCUE_API_HOST. The Werkzeug debugger allows arbitrary code "
            "execution and must never be reachable off-box."
        )
    if not os.environ.get("RESCUE_API_KEY") and os.environ.get("ALLOW_UNAUTHENTICATED", "false").lower() != "true":
        logger.warning(
            "RESCUE_API_KEY is not set — the API will reject all non-exempt "
            "requests with 500 ServerMisconfigured until it is set, or "
            "ALLOW_UNAUTHENTICATED=true is set for local demos only."
        )
    logger.info("Earthward Rescue API starting on http://%s:%d", host, port)
    logger.info("OpenAPI spec available at http://%s:%d/openapi.yaml", host, port)
    app.run(debug=debug, host=host, port=port)
