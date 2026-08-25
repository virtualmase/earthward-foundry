"""Production WSGI entry point for the Earthward Rescue API."""

import incident_log as log
from api import app

log.init_db(reset=False)

__all__ = ["app"]
