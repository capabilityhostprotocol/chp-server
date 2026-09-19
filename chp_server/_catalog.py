"""Discover installed ``chp-adapter-*`` capability sets — the composable catalog.

Enumerates adapters registered under the ``chp.adapters`` entry-point group and reads each
one's ``@capability`` descriptors WITHOUT instantiating the adapter — so adapters that need
configuration (API keys, backends) still list. A live catalog that can't rot: it reflects what
is actually installed in this environment. Powers ``chp-server adapters``.
"""

from __future__ import annotations

import inspect


def _capabilities_of(cls: type) -> list[dict]:
    """(id, description) for each ``@capability`` method on an adapter class — config-free."""
    caps: list[dict] = []
    seen: set[str] = set()
    for _name, member in inspect.getmembers(cls):
        descriptor = getattr(member, "__chp_descriptor__", None)
        cid = getattr(descriptor, "id", None)
        if cid and cid not in seen:
            seen.add(cid)
            caps.append({"id": cid, "description": (descriptor.description or "").strip()})
    return sorted(caps, key=lambda c: c["id"])


def adapter_catalog() -> list[dict]:
    """Installed adapters as ``[{name, module, capabilities: [{id, description}]}]``, sorted by
    name. Empty when no adapter packages are installed (a bare chp-server + chp-core env)."""
    from chp_core.adapters import discover_adapters

    catalog: list[dict] = []
    for name, cls in sorted(discover_adapters().items()):
        try:
            caps = _capabilities_of(cls)
        except Exception:
            caps = []  # a broken adapter never sinks the catalog
        catalog.append({"name": name, "module": getattr(cls, "__module__", "?"),
                        "capabilities": caps})
    return catalog
