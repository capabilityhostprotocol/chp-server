"""`chp-server adapters` catalog — discover installed adapters config-free.

The catalog must read an adapter's capabilities WITHOUT instantiating it (so adapters that
need API keys/backends still list), and tolerate a bare env with no adapters installed.
chp-core only.
"""

from __future__ import annotations

from chp_core.adapters import BaseAdapter
from chp_core.decorators import capability

from chp_server._catalog import _capabilities_of, adapter_catalog


def test_capabilities_read_config_free_without_instantiating():
    class NeedsConfigAdapter(BaseAdapter):
        def __init__(self, config):          # cannot be built with no args
            raise RuntimeError("this adapter needs configuration")

        @capability(id="demo.one", version="1.0.0", description="First.")
        def one(self, ctx, payload):
            return {}

        @capability(id="demo.two", version="1.0.0", description="Second.")
        def two(self, ctx, payload):
            return {}

    caps = _capabilities_of(NeedsConfigAdapter)      # pass the CLASS, never an instance
    assert [c["id"] for c in caps] == ["demo.one", "demo.two"]
    assert caps[0]["description"] == "First."


def test_adapter_catalog_shape_tolerates_empty():
    catalog = adapter_catalog()
    assert isinstance(catalog, list)                 # empty in a bare chp-server+chp-core env
    for entry in catalog:
        assert {"name", "module", "capabilities"} <= set(entry)
        assert isinstance(entry["capabilities"], list)
        for cap in entry["capabilities"]:
            assert "id" in cap and "description" in cap
