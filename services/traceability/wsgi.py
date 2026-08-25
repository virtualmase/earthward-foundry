"""Production WSGI entry point for the Earthward Traceability API."""

import service as svc
from api import app

svc.init_db(reset=False)

__all__ = ["app"]
