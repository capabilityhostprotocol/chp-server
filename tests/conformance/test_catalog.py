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


def test_dynamic_capabilities_adapter_read_via_safe_instantiation():
    # An adapter that builds its capabilities in capabilities() (like chp-core's GitAdapter)
    # has NO @capability method descriptors, so the static scan finds none — the catalog used
    # to show it as "0 caps". A safe no-arg instantiation recovers them.
    from chp_core import CapabilityDescriptor
    from chp_core.adapters import HostedCapability

    class DynamicAdapter(BaseAdapter):
        def __init__(self, config=None):        # no-arg constructable
            pass

        def capabilities(self):
            yield HostedCapability(
                descriptor=CapabilityDescriptor(id="dyn.one", version="1.0.0",
                                                description="Built at runtime."),
                handler=lambda ctx, payload: {})

    caps = _capabilities_of(DynamicAdapter)
    assert [c["id"] for c in caps] == ["dyn.one"]
    assert caps[0]["description"] == "Built at runtime."


def test_config_needing_adapter_without_static_caps_stays_capless():
    # The safe-instantiation fallback must NOT turn a config-needing adapter into an error:
    # if __init__ raises and there are no static @capability methods, report capless.
    class NeedsConfigNoStatic(BaseAdapter):
        def __init__(self, config):
            raise RuntimeError("needs configuration")

        def capabilities(self):
            return []

    assert _capabilities_of(NeedsConfigNoStatic) == []


def test_adapter_catalog_shape_tolerates_empty():
    catalog = adapter_catalog()
    assert isinstance(catalog, list)                 # empty in a bare chp-server+chp-core env
    for entry in catalog:
        assert {"name", "module", "capabilities"} <= set(entry)
        assert isinstance(entry["capabilities"], list)
        for cap in entry["capabilities"]:
            assert "id" in cap and "description" in cap
