"""`chp-server new` scaffold — the install-to-your-own-server on-ramp.

The generated starter must be valid Python that builds a working governed host,
substitute the name safely, and never clobber an existing file without --force.
chp-core-only.
"""

from __future__ import annotations

import ast

import pytest

from chp_server._scaffold import _host_id, render_starter, write_starter


def test_render_is_valid_python_and_substituted():
    src = render_starter("mycaps")
    ast.parse(src)                                   # valid Python
    assert "__HOST_ID__" not in src and "__FILENAME__" not in src
    assert 'CapabilityServer("mycaps")' in src
    assert "@app.capability(" in src and "app.run(" in src


@pytest.mark.parametrize("name,expected", [
    ("mycaps", "mycaps"), ("mycaps.py", "mycaps"),
    ("My Caps!", "my-caps"), ("...", "my-host"),
])
def test_host_id_is_sanitized(name, expected):
    assert _host_id(name) == expected


def test_write_refuses_to_clobber_without_force(tmp_path):
    target = str(tmp_path / "mycaps")
    path = write_starter(target)
    assert path.exists() and path.name == "mycaps.py"
    with pytest.raises(FileExistsError):
        write_starter(target)
    write_starter(target, force=True)                # force overwrites


def test_generated_starter_builds_a_working_host(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                       # sqlite stores land here
    ns: dict = {}
    exec(compile(render_starter("mycaps"), "mycaps.py", "exec"), ns)
    host = ns["app"].host                             # module-level CapabilityServer
    result = host.invoke("greet.hello", {"name": "world"})
    assert result.success and result.data == {"greeting": "hello, world"}
