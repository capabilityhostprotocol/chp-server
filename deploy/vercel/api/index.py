"""Vercel Python entrypoint for a CHP host — self-contained FastAPI ASGI ``app``.

Built with an explicit ``@vercel/python`` build (see vercel.json), so it does not rely on
framework auto-detection (which does not run reliably for a raw files upload) or on the
bundler tracing a sibling package. Everything the function needs is in THIS file plus the
``requirements.txt`` deps (fastapi, chp-server). The logic mirrors the tested
``chp_vercel_host`` module; keep them in sync (a future activation DEPLOY provider will
generate this file from that module).

Vercel routes every request here; a catch-all FastAPI route drives the REAL chp-core request
handler via an in-memory socket, so auth / version / scope / the 12-gate pipeline / evidence /
replay all run verbatim from chp-core. The governed host is built once at cold start.
Slice 1 evidence is /tmp SQLite (warm-instance durable, not across cold starts).
"""
from __future__ import annotations

import io
import os
from typing import Any

from fastapi import FastAPI, Request, Response

from chp_core.http import CapabilityHostRequestHandler

HOST_ID = os.environ.get("CHP_SERVER_HOST_ID", "chp-vercel")


def build_host(host_id: str = HOST_ID):
    from chp_server import CapabilityServer

    store = os.environ.get("CHP_EVIDENCE_PATH") or "/tmp/chp-vercel-evidence.sqlite"
    srv = CapabilityServer(host_id, store=store)

    @srv.capability("demo.echo")
    def echo(message: str = "") -> dict:
        """Echo a message back unchanged (deterministic; no side effects)."""
        return {"echo": message}

    @srv.capability("math.add")
    def add(a: float, b: float) -> dict:
        """Add two numbers (deterministic; no side effects)."""
        return {"sum": a + b}

    return srv.host


class _StubServer:
    def __init__(self, host: Any) -> None:
        self.chp_host = host

    def allow_request(self, caller: str) -> bool:
        return True

    def track_request(self, delta: int) -> None:
        return None


class _KeepBuffer(io.BytesIO):
    def close(self) -> None:
        try:
            self.flush()
        except Exception:
            pass


class _FakeConn:
    def __init__(self, request_bytes: bytes) -> None:
        self._rfile = _KeepBuffer(request_bytes)
        self.wbuf = _KeepBuffer()

    def makefile(self, mode: str = "r", *args: Any, **kwargs: Any):
        return self.wbuf if "w" in mode else self._rfile

    def sendall(self, data: bytes) -> None:
        self.wbuf.write(data)

    def settimeout(self, *_a: Any) -> None:
        return None

    def setsockopt(self, *_a: Any) -> None:
        return None

    def shutdown(self, *_a: Any) -> None:
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


def _parse_response(raw: bytes):
    head, _, body = raw.partition(b"\r\n\r\n")
    head_lines = head.split(b"\r\n")
    status_line = head_lines[0].decode("latin-1") if head_lines else "HTTP/1.1 500 Error"
    parts = status_line.split(" ", 2)
    status = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 500
    out_headers = []
    for line in head_lines[1:]:
        if b":" in line:
            k, _, v = line.partition(b":")
            out_headers.append((k.decode("latin-1").strip(), v.decode("latin-1").strip()))
    return status, out_headers, body


def dispatch(host: Any, method: str, path: str, headers: dict, body: bytes = b""):
    conn = _FakeConn(_raw_request(method, path, headers, body))
    CapabilityHostRequestHandler(conn, ("127.0.0.1", 0), _StubServer(host))
    return _parse_response(conn.wbuf.getvalue())


app = FastAPI(title="chp-server-on-vercel")
_HOST = build_host()
_DROP = {"connection", "content-length", "transfer-encoding", "date", "server", "keep-alive"}


@app.api_route("/{_full_path:path}",
               methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def _catch_all(_full_path: str, request: Request) -> Response:
    body = await request.body()
    path = request.url.path
    if request.url.query:
        path = f"{path}?{request.url.query}"
    status, resp_headers, resp_body = dispatch(_HOST, request.method, path, dict(request.headers), body)
    out = {k: v for (k, v) in resp_headers if k.lower() not in _DROP}
    return Response(content=resp_body, status_code=status, headers=out)
