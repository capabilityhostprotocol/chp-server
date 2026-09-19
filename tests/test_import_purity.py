"""Architectural fitness (docs 43/53): the base package imports no optional CHP package.

This is the in-process half of PKG-009; the clean-venv half lives in
scripts/chp-server-conformance.sh.
"""

from __future__ import annotations

import subprocess
import sys

FORBIDDEN = ("chp_host", "chp_platform", "mcp", "zenoh", "chp_transport_zenoh")


def test_import_pulls_no_optional_chp_package():
    # A fresh interpreter so previously-imported test deps can't mask a violation.
    code = (
        "import sys; import chp_server; "
        f"bad=[m for m in sys.modules if m.split('.')[0] in {FORBIDDEN!r}]; "
        "assert not bad, f'optional packages imported: {bad}'; print('pure')"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "pure"


def test_declared_dependencies_are_core_only():
    from importlib.metadata import requires
    reqs = [r.split(";")[0].strip() for r in (requires("chp-server") or [])]
    chp_reqs = [r for r in reqs if r.lower().startswith("chp")]
    assert all(r.startswith("chp-core") for r in chp_reqs), chp_reqs


def test_api_008_public_api_stays_small_and_extensible():
    # API-008: the public base API stays small enough that optional features attach
    # WITHOUT becoming part of it. The surface is bounded and exposes the entry-point
    # attach seam; the companion purity test proves the base imports no optional
    # package, so optional features cannot be part of this base API.
    import chp_server
    api = list(chp_server.__all__)
    assert len(api) <= 24, f"public API grew to {len(api)}: {api}"
    assert "ENTRY_POINT_GROUP" in api  # optional features attach via the entry-point group
    assert "AttachmentRegistry" in api and "PORT_ROLES" in api  # the generic attach surface
