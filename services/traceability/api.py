"""
Thin HTTP wrapper over service.py.

Built on Flask rather than FastAPI because this sandbox has no network
access to pip-install FastAPI/SQLAlchemy. Swapping to FastAPI later is a
mechanical change — service.py has zero framework dependency, so only
this file would need to change. Run:

    pip install fastapi uvicorn
    # then re-express the routes below using APIRouter + pydantic models

To run this API as-is:
    pip install flask
    python3 api.py
    # -> http://127.0.0.1:5000
"""

import os

from flask import Flask, request, jsonify
import service as svc
from api_auth import require_api_key
from logging_config import configure_logging, logger

app = Flask(__name__)
require_api_key(app, "TRACEABILITY_API_KEY")
configure_logging(app, "traceability")


def error_response(e: Exception, code: int = 400):
    return jsonify({"error": type(e).__name__, "message": str(e)}), code


@app.post("/parts")
def create_part():
    body = request.get_json(force=True)
    try:
        part_id = svc.create_part(
            part_number=body["part_number"],
            revision=body["revision"],
            part_id=body.get("part_id"),
        )
        return jsonify({"part_id": part_id}), 201
    except KeyError as e:
        return error_response(e, 400)


@app.get("/parts/<part_id>")
def get_record(part_id: str):
    try:
        return jsonify(svc.get_record(part_id))
    except svc.UnknownPartError as e:
        return error_response(e, 404)


@app.post("/parts/<part_id>/events")
def append_event(part_id: str):
    body = request.get_json(force=True)
    try:
        source = svc.Source(type=body["source"]["type"], id=body["source"]["id"])
        result = svc.append_event(
            part_id=part_id,
            event_type=body["event_type"],
            source=source,
            reference=body["reference"],
            data=body.get("data"),
            corrects_event_id=body.get("corrects_event_id"),
        )
        return jsonify(result), 201
    except svc.UnknownPartError as e:
        return error_response(e, 404)
    except svc.UnauthorizedSourceError as e:
        return error_response(e, 403)
    except svc.InvalidSequenceError as e:
        return error_response(e, 409)
    except svc.TraceabilityError as e:
        return error_response(e, 400)
    except KeyError as e:
        return error_response(e, 400)


@app.get("/parts/<part_id>/gaps")
def get_gaps(part_id: str):
    try:
        gaps = svc.check_gaps(part_id)
        return jsonify(gaps.__dict__)
    except svc.UnknownPartError as e:
        return error_response(e, 404)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    svc.init_db(reset=False)  # never reset a running API's data on boot
    port = int(os.environ.get("TRACEABILITY_API_PORT", 5000))
    debug = os.environ.get("TRACEABILITY_API_DEBUG", "false").lower() == "true"
    host = os.environ.get("TRACEABILITY_API_HOST", "127.0.0.1")
    if debug and host not in ("127.0.0.1", "localhost"):
        raise SystemExit(
            "Refusing to start: TRACEABILITY_API_DEBUG=true with a non-localhost "
            "TRACEABILITY_API_HOST. The Werkzeug debugger allows arbitrary code "
            "execution and must never be reachable off-box."
        )
    if not os.environ.get("TRACEABILITY_API_KEY") and os.environ.get("ALLOW_UNAUTHENTICATED", "false").lower() != "true":
        logger.warning(
            "TRACEABILITY_API_KEY is not set — the API will reject all non-exempt "
            "requests with 500 ServerMisconfigured until it is set, or "
            "ALLOW_UNAUTHENTICATED=true is set for local demos only."
        )
    logger.info("Earthward Traceability API starting on http://%s:%d", host, port)
    app.run(debug=debug, host=host, port=port)
