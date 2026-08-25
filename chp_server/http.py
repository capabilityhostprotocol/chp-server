"""Server-distribution endpoints over the canonical chp-core handler.

Adds GET /server (Server.Describe, authed like /host) and GET /ready (public,
profile-aware readiness + draining truth; /health stays pure liveness).
Everything else delegates to chp-core — the protocol surface is owned there.
"""

from __future__ import annotations

from http import HTTPStatus
from urllib.parse import urlparse

from chp_core.http import CapabilityHostRequestHandler


def make_handler(server) -> type:
    class ServerRequestHandler(CapabilityHostRequestHandler):
        chp_server = server

        def _do_get(self) -> None:
            path = urlparse(self.path).path
            if path == "/ready":
                # Public like /health: load balancers must see draining truth
                # without credentials. No capability data is disclosed.
                r = self.chp_server.ready()
                status = HTTPStatus.OK if r["ready"] else HTTPStatus.SERVICE_UNAVAILABLE
                self._write_json(r, status=status)
                return
            if path == "/server":
                if self._reject_unsupported_version():
                    return
                if not self._check_auth():
                    return
                self._write_json(self.chp_server.describe())
                return
            super()._do_get()

    return ServerRequestHandler
