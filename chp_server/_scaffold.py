"""Scaffold a starter CHP capability server — the ``chp-server new`` command.

Writes a single runnable Python file that serves one sample capability through the
full CHP pipeline, so a newcomer goes from install to *their own* governed server in
one command. The generated file needs only chp-core + chp-server.
"""

from __future__ import annotations

import re
from pathlib import Path

# Placeholders are substituted by str.replace (not str.format) so the template can
# contain literal f-strings and dict/JSON braces without escaping every one.
_TEMPLATE = '''#!/usr/bin/env python3
"""A starter CHP capability server. Run it:  python __FILENAME__

Serves your capabilities over HTTP with governed invocation and a signed, replayable
evidence chain. Needs only chp-core + chp-server. See the serving guide:
https://github.com/capabilityhostprotocol/chp-core
"""
from __future__ import annotations

from chp_server import CapabilityServer

app = CapabilityServer("__HOST_ID__")


@app.capability("greet.hello")
def hello(name: str = "world") -> dict:
    """Greet a name."""
    # The docstring becomes the description; the type hints become the input
    # schema, which the pipeline enforces before this function runs.
    return {"greeting": f"hello, {name}"}


# TODO: add your own capabilities — one decorated function each.


if __name__ == "__main__":
    # try:  curl localhost:8800/invoke -H 'Content-Type: application/json' \\
    #            -d '{"capability_id": "greet.hello", "payload": {"name": "CHP"}}'
    app.run(port=8800)
'''


def _host_id(name: str) -> str:
    """A safe host_id/slug from the requested name (letters, digits, dashes)."""
    slug = re.sub(r"[^a-z0-9-]+", "-", Path(name).stem.lower()).strip("-")
    return slug or "my-host"


def _target_path(name: str) -> Path:
    return Path(name if name.endswith(".py") else f"{name}.py")


def render_starter(name: str) -> str:
    """The generated starter file's source (does not touch disk)."""
    path = _target_path(name)
    return _TEMPLATE.replace("__FILENAME__", path.name).replace("__HOST_ID__", _host_id(name))


def write_starter(name: str, *, force: bool = False) -> Path:
    """Write the starter file next to the caller; refuse to clobber unless *force*."""
    path = _target_path(name)
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists (use --force to overwrite)")
    path.write_text(render_starter(name))
    return path
