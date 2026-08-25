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
