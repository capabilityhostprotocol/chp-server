"""Async/streaming conformance (ASYNC) over the served surface.

chp-core owns streaming (proposal 0012): SSE `chunk` frames + one terminal
`result` frame, each carrying an `id:` cursor, with `Last-Event-ID` resume from
the recorded chunk buffer. The server serves that surface verbatim; these cases
prove frame distinguishability and cursor resume over POST /invoke. chp-core-only.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from chp_core import CapabilityDescriptor, LocalCapabilityHost, SQLiteEvidenceStore
from chp_core.types import StreamResult
from chp_server import Server, ServerConfig


class GovernedHostPort:
    roles = ("HostPort", "AdmissionPort", "ExecutionPort", "EvidencePort")
    source = "local"

    def __init__(self, host):
        self.host = host

    def health(self):
        return "ready"


@pytest.fixture()
def rig(tmp_path):
    host = LocalCapabilityHost("async-host", store=SQLiteEvidenceStore(str(tmp_path / "h.sqlite")))

    async def streamer(_ctx, _payload):
        for i in range(3):
            yield {"token": f"t{i}"}
        yield StreamResult({"text": "t0t1t2"})

    host.register(CapabilityDescriptor(id="s.chat", version="1.0.0", description="Stream.",
                                       modes=["sync", "stream"]), streamer)
    s = Server(ServerConfig(port=0, profile="local", store=str(tmp_path / "s.sqlite")))
    s.attach(GovernedHostPort(host))
    s.start()
    yield s
    s.stop()


def _stream(server, inv, last_event_id=None):
    """POST a stream request; return (frames, raw) where frames = [(id, event, data)]."""
    headers = {"Content-Type": "application/json"}
    if last_event_id is not None:
        headers["Last-Event-ID"] = str(last_event_id)
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/invoke",
        data=json.dumps({"capability_id": "s.chat", "mode": "stream",
                         "payload": {}, "invocation_id": inv}).encode(),
        headers=headers)
    raw = urllib.request.urlopen(req).read().decode()
    frames = []
    cur = {}
    for line in raw.splitlines():
        if line.startswith("id: "):
            cur["id"] = int(line[4:])
        elif line.startswith("event: "):
            cur["event"] = line[7:]
        elif line.startswith("data: "):
            cur["data"] = json.loads(line[6:])
        elif line == "" and cur:
            frames.append((cur.get("id"), cur.get("event"), cur.get("data")))
            cur = {}
    return frames, raw


def test_async_001_chunk_frames_precede_terminal_result(rig):
    frames, raw = _stream(rig, "inv-stream-1")
    assert raw.startswith("id:") or "event: chunk" in raw  # opened as SSE
    events = [ev for _id, ev, _d in frames]
    # Stream chunks and the terminal result are DISTINGUISHABLE frame types,
    # and every chunk precedes the single result (ASYNC-001).
    assert events == ["chunk", "chunk", "chunk", "result"]
    chunk_ids = [i for i, ev, _ in frames if ev == "chunk"]
    assert chunk_ids == [0, 1, 2]  # monotonic cursor ids


def test_async_003_007_resume_from_cursor(rig):
    full, _ = _stream(rig, "inv-stream-2")
    assert [ev for _i, ev, _d in full] == ["chunk", "chunk", "chunk", "result"]
    # Reconnect echoing the last chunk id seen (0): resume delivers only the
    # chunks AFTER the cursor — a lost stream replays from the recorded buffer
    # rather than being treated as an execution failure (ASYNC-003/007).
    resumed, _ = _stream(rig, "inv-stream-2", last_event_id=0)
    resumed_chunks = [i for i, ev, _ in resumed if ev == "chunk"]
    assert resumed_chunks == [1, 2]  # resumed past cursor 0, not from the start
    assert resumed[-1][1] == "result"  # terminal result still delivered
