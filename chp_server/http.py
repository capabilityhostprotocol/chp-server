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
            if path == "/.well-known/chp":
                self._write_json(self._well_known_chp())
                return
            if path == "/capabilities.txt":
                self._write_capabilities_hint()
                return
            if path == "/resolve":
                self._serve_resolve()
                return
            if path.startswith("/replay/"):
                self._authorized_replay(path)
                return
            super()._do_get()

        # -- capability resolution over the wire (resolver tier part 2) ----------
        def _serve_resolve(self) -> None:
            # Resolution answers WHERE a capability is served. Truthful when absent: a
            # server with no ResolutionPort reports capability.resolve unsupported rather
            # than pretending. Visibility-scoped: the verified caller is passed through.
            from .features import READY
            from urllib.parse import parse_qs
            reg = self.chp_server.attachments
            port = reg.for_role("ResolutionPort")
            if port is None or reg.role_state("ResolutionPort") != READY:
                self._write_error(HTTPStatus.NOT_IMPLEMENTED, "feature_unsupported",
                                  "capability.resolve is not supported (no ResolutionPort attached)")
                return
            if not self._check_auth():
                return
            q = parse_qs(urlparse(self.path).query)
            requirement = {}
            for k in ("capability_id", "namespace", "category", "risk", "status"):
                if k in q and q[k]:
                    requirement[k] = q[k][0]
            results = port.resolve(requirement, caller=getattr(self, "_caller", None))
            self._write_json({"capability_id": requirement.get("capability_id"),
                              "resolved": results, "count": len(results)})

        # -- wire advertisement feed (resolver tier part 3.5) --------------------
        def _serve_advertise(self) -> None:
            """POST a signed supply-advertisement batch. The batch's SIGNATURE is the gate:
            it is verified against the resolver's SourceTrustPolicy (reusing the introduction
            trust+crypto), so no API key is required — a resolver exposed here should carry a
            trust policy or it trusts all. Resolution still confers NO authority: a resolved
            endpoint is invoked under the full gate pipeline at the serving host."""
            from .features import READY
            reg = self.chp_server.attachments
            port = reg.for_role("ResolutionPort")
            if port is None or reg.role_state("ResolutionPort") != READY:
                self._write_error(HTTPStatus.NOT_IMPLEMENTED, "feature_unsupported",
                                  "capability.resolve is not supported (no ResolutionPort attached)")
                return
            if not hasattr(port, "accept_signed_advertisement"):
                self._write_error(HTTPStatus.NOT_IMPLEMENTED, "feature_unsupported",
                                  "this ResolutionPort does not accept advertisements")
                return
            try:
                batch = self._read_json()
            except ValueError as exc:
                self._write_error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
                return
            result = port.accept_signed_advertisement(batch)
            if result.get("accepted"):
                self._write_json({"accepted": True, "advertised": result.get("advertised"),
                                  "host_id": result.get("host_id")})
            else:
                denial = result.get("denial") or {}
                self._write_error(HTTPStatus.FORBIDDEN,
                                  denial.get("code", "advertiser_not_trusted"),
                                  denial.get("message", "advertisement rejected"))

        # -- EVID-007: evidence-query authorization (tenant/visibility boundary) --
        def _authorized_replay(self, path: str) -> None:
            from urllib.parse import unquote
            if not self._check_auth():            # sets self._caller; writes 401 if bad
                return
            correlation_id = unquote(path[len("/replay/"):])
            result = self.server.chp_host.replay_result(correlation_id)
            caller = getattr(self, "_caller", None)
            if caller is not None and not self._replay_visible(result, caller):
                # Least-disclosure: 404, never reveal that another tenant's correlation
                # exists. A caller sees only evidence within its own boundary.
                self._write_error(HTTPStatus.NOT_FOUND, "evidence_not_visible",
                                  "no evidence visible to this caller for that correlation")
                return
            self._write_json(result.to_dict())

        def _replay_visible(self, result, caller: str) -> bool:
            # An explicit observer scope sees all evidence (an operator/audit role).
            scope = getattr(self, "_caller_scope", None) or []
            if "evidence:observer" in scope or "observer" in scope:
                return True
            # Otherwise the caller may see a correlation only if it is the recorded
            # principal (invocation subject/actor) of that evidence. Evidence with no
            # recorded principal (single-tenant/local work) is unscoped, today's behavior.
            principals: set[str] = set()
            for e in getattr(result, "events", []) or []:
                for who in (e.get("subject"), e.get("actor")):
                    if isinstance(who, dict) and who.get("id"):
                        principals.add(who["id"])
            return not principals or caller in principals

        # -- DISC-001: three DISTINCT discovery surfaces with defined purposes --
        # /host (super) is the AUTHORITATIVE, access-controlled live-discovery
        # surface. The two below are PUBLIC, non-authoritative hints and are never
        # an introduction authority (DEC-INTRO-005). They stay separate on purpose.
        def _well_known_chp(self) -> dict:
            from chp_core.types import PROTOCOL_VERSION
            return {
                "server": "chp-server",
                "protocol_version": PROTOCOL_VERSION,
                "surfaces": {
                    "live_discovery": {"path": "/host", "authoritative": True,
                                       "authenticated": True},
                    "describe": {"path": "/server"},
                    "health": {"path": "/health"},
                    "ready": {"path": "/ready"},
                    "invoke": {"path": "/invoke"},
                    "capabilities_hint": {"path": "/capabilities.txt",
                                          "authoritative": False},
                },
                "note": ("public discovery bootstrap; capabilities.txt is a "
                         "non-authoritative hint and not an introduction authority. "
                         "Authoritative capability truth is the authenticated live-"
                         "discovery surface (/host), subject to visibility policy."),
            }

        def _extra_metrics(self) -> str:
            # OBS-002: expose server lifecycle, feature health, and attachment/role
            # health as Prometheus series (chp-core /metrics already covers request
            # latency + evidence). Values are LIVE — read from the one FeatureRegistry
            # + AttachmentRegistry, so they track degradation, not a static snapshot.
            from .features import READY, UNSUPPORTED
            from .ports import PORT_ROLES
            srv = self.chp_server
            out = [
                "# HELP chp_server_ready Server readiness (1 ready, 0 otherwise).",
                "# TYPE chp_server_ready gauge",
                f"chp_server_ready {1 if srv.ready().get('ready') else 0}",
                "# HELP chp_server_feature_ready Feature health (1 ready, 0 otherwise).",
                "# TYPE chp_server_feature_ready gauge",
            ]
            for f in srv.features.snapshot(lifecycle=srv.state):
                out.append(f'chp_server_feature_ready{{feature="{f.feature}",'
                           f'state="{f.state}"}} {1 if f.state == READY else 0}')
            out += ["# HELP chp_server_attachment_role_ready Attachment role health "
                    "(1 ready, 0 otherwise).",
                    "# TYPE chp_server_attachment_role_ready gauge"]
            for role in PORT_ROLES:
                st = srv.attachments.role_state(role)
                if st != UNSUPPORTED:  # only roles an attachment actually provides
                    out.append(f'chp_server_attachment_role_ready{{role="{role}",'
                               f'state="{st}"}} {1 if st == READY else 0}')
            return "\n".join(out) + "\n"

        def _write_capabilities_hint(self) -> None:
            # A public HINT: only PUBLICLY-VISIBLE capability ids. chp-core treats an
            # anonymous caller=None as UNFILTERED (the invocation gate is the
            # backstop), but a public hint file must be least-disclosure — so we
            # discover as a non-actor sentinel: capabilities restricted to specific
            # allowed_actors are hidden (cf DISC-003), open capabilities are shown.
            host = self.server.chp_host
            caps = host.discover(caller="\x00public-anonymous").get("capabilities", [])
            lines = [
                "# CHP capabilities hint — non-authoritative; not an introduction authority.",
                "# Authoritative, access-controlled discovery: GET /host.",
                *sorted(c["id"] for c in caps),
            ]
            body = ("\n".join(lines) + "\n").encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _do_post(self) -> None:
            # LIFE-006: a draining server MUST stop accepting new work before
            # shutdown. New invocations are refused with 503; in-flight work
            # (already admitted) continues under its bound semantics.
            from .server import ServerStatus
            path = urlparse(self.path).path
            if self.chp_server.state == ServerStatus.DRAINING:
                if path == "/invoke":  # new work; /replay etc. are reads, still served
                    self._write_error(HTTPStatus.SERVICE_UNAVAILABLE, "server_draining",
                                      "server is draining; not accepting new invocations")
                    return
            # HA standby gate (HA-005): only the ACTIVE lease-holder admits invocation
            # work; a standby (or ownership-uncertain, fail-closed) instance refuses.
            # Reads (GET /host, /replay, …) are unaffected — they are not POSTs here.
            if path == "/invoke" and self.chp_server.role() != "active":
                self._write_error(HTTPStatus.SERVICE_UNAVAILABLE, "server_not_active",
                                  "this instance is standby; not the active Host owner")
                return
            if path == "/advertise":     # resolver part 3.5 — trust-gated supply feed
                self._serve_advertise()
                return
            super()._do_post()

    return ServerRequestHandler
