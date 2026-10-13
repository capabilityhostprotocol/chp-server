"""Run a CHP host inside a Vercel Python Function (request-driven, no persistent process).

Vercel has no always-on process, so we do NOT use ``Server``/``serve_forever``. Instead we
build the governed host once at module load (cold start) and drive the REAL chp-core request
handler for each request through an in-memory socket — so auth, version negotiation, capability
scope, the 12-gate invocation pipeline, evidence, and replay all run VERBATIM from chp-core.
Nothing in this file re-implements governance; it only adapts transport.

Served surface (the sync subset that makes sense in a function): GET /health, GET /host,
GET /replay/<corr>, GET /verify/<corr>, POST /invoke. Streaming/SSE, HA lease, SIGTERM drain
and per-process rate caps are long-lived-process features and are intentionally absent.

Slice 1 (issue 47d0e82): evidence is a /tmp SQLite chain — durable within a WARM instance
(real governed execution + a verifiable chain per invocation), NOT across cold starts. Slice 1b
swaps in a durable external store (Neon Postgres) via the store-object injection added to
CapabilityServer. mTLS is unavailable behind Vercel's TLS edge, so auth is header-based
(CHP_HOST_API_KEYS / CHP_HOST_TOKEN_KEYS); absent -> open (local-first default).
"""
from __future__ import annotations

import io
import os
from typing import Any

from chp_core.http import CapabilityHostRequestHandler

__all__ = ["build_host", "dispatch", "HOST_ID"]

HOST_ID = os.environ.get("CHP_SERVER_HOST_ID", "chp-vercel")


def build_host(host_id: str = HOST_ID):
    """Cold-start: build the governed host with its baked capabilities and evidence store.

    Store path defaults to /tmp (the only writable, though ephemeral, FS on Vercel). A durable
    external store is injected here in slice 1b via CapabilityServer(store=<store object>).
    """
    from chp_server import CapabilityServer

    store = os.environ.get("CHP_EVIDENCE_PATH") or "/tmp/chp-vercel-evidence.sqlite"
    app = CapabilityServer(host_id, store=store)

    @app.capability("demo.echo")
    def echo(message: str = "") -> dict:
        """Echo a message back unchanged (deterministic; no side effects)."""
        return {"echo": message}

    @app.capability("math.add")
    def add(a: float, b: float) -> dict:
        """Add two numbers (deterministic; no side effects)."""
        return {"sum": a + b}

    return app.host


class _StubServer:
    """Minimal stand-in for CapabilityHostHTTPServer in a one-request-per-invocation function.

    Holds the real host. Per-process rate limiting and SIGTERM drain accounting are meaningless
    with no shared process across invocations, so they are no-ops — every real governance
    decision runs through ``chp_host``.
    """

    def __init__(self, host: Any) -> None:
        self.chp_host = host

    def allow_request(self, caller: str) -> bool:  # noqa: D401 - rate limit n/a per-request
        return True

    def track_request(self, delta: int) -> None:  # drain accounting n/a in a function
        return None


class _KeepBuffer(io.BytesIO):
    """A BytesIO whose ``close()`` is a no-op (it only flushes), so the written response
    stays readable after the handler's ``finish()`` closes its wfile."""

    def close(self) -> None:  # noqa: D401
        try:
            self.flush()
        except Exception:  # noqa: BLE001
            pass


class _FakeConn:
    """Socket stand-in: ``makefile`` returns in-memory request/response buffers, plus the
    no-op socket methods BaseHTTPRequestHandler's setup/finish touch (``settimeout`` etc.).

    Deliberately exposes NO ``getpeercert`` so chp-core's ``_mtls_peer_identity`` treats it as
    plain TCP (correct — Vercel terminates TLS at the edge; no client cert reaches the function).
    """

    def __init__(self, request_bytes: bytes) -> None:
        self._rfile = _KeepBuffer(request_bytes)
        self.wbuf = _KeepBuffer()

    def makefile(self, mode: str = "r", *args: Any, **kwargs: Any):
        return self.wbuf if "w" in mode else self._rfile

    def sendall(self, data: bytes) -> None:
        # Python 3.12's StreamRequestHandler uses a _SocketWriter (wbufsize=0) that
        # writes the response via connection.sendall, not via a makefile wfile.
        self.wbuf.write(data)

    def settimeout(self, *_args: Any) -> None:
        return None

    def setsockopt(self, *_args: Any) -> None:
        return None

    def shutdown(self, *_args: Any) -> None:
        return None

    def getpeername(self):
        return ("127.0.0.1", 0)

    def fileno(self) -> int:
        return -1

    def close(self) -> None:
        return None


def _raw_request(method: str, path: str, headers: dict, body: bytes) -> bytes:
    lower = {k.lower() for k in headers}
    lines = [f"{method} {path} HTTP/1.1", "Host: chp-vercel", "Connection: close"]
    for k, v in headers.items():
        if k.lower() in ("host", "connection"):
            continue
        lines.append(f"{k}: {v}")
    if body and "content-length" not in lower:
        lines.append(f"Content-Length: {len(body)}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + (body or b"")


def _parse_response(raw: bytes) -> tuple[int, list[tuple[str, str]], bytes]:
    head, _, body = raw.partition(b"\r\n\r\n")
    head_lines = head.split(b"\r\n")
    status_line = head_lines[0].decode("latin-1") if head_lines else "HTTP/1.1 500 Error"
    parts = status_line.split(" ", 2)
    status = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 500
    out_headers: list[tuple[str, str]] = []
    for line in head_lines[1:]:
        if b":" in line:
            k, _, v = line.partition(b":")
            out_headers.append((k.decode("latin-1").strip(), v.decode("latin-1").strip()))
    return status, out_headers, body


def dispatch(host: Any, method: str, path: str, headers: dict, body: bytes = b"") \
        -> tuple[int, list[tuple[str, str]], bytes]:
    """Drive the real chp-core handler for ONE request through an in-memory socket."""
    conn = _FakeConn(_raw_request(method, path, headers, body))
    server = _StubServer(host)
    # BaseHTTPRequestHandler.__init__ runs setup()->handle()->finish(); "Connection: close"
    # in the raw request stops the keep-alive loop after one request.
    CapabilityHostRequestHandler(conn, ("127.0.0.1", 0), server)
    return _parse_response(conn.wbuf.getvalue())
