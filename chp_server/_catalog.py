"""Discover installed ``chp-adapter-*`` capability sets — the composable catalog.

Enumerates adapters registered under the ``chp.adapters`` entry-point group and reads each
one's ``@capability`` descriptors WITHOUT instantiating the adapter — so adapters that need
configuration (API keys, backends) still list. A live catalog that can't rot: it reflects what
is actually installed in this environment. Powers ``chp-server adapters``.
"""

from __future__ import annotations

import inspect


def _capabilities_of(cls: type) -> list[dict]:
    """(id, description) for each capability an adapter class exposes.

    First reads ``@capability`` method descriptors statically — config-free, no
    instantiation (so adapters that need API keys/backends still list). If none are found,
    the adapter likely builds its capabilities dynamically in ``capabilities()`` (e.g.
    chp-core's GitAdapter via git_capabilities()); a static scan can't see those, so it
    showed "0 caps". Try a SAFE no-arg instantiation to read them — an adapter that needs
    configuration raises on ``__init__``/``capabilities()`` and is caught, staying capless
    exactly as before (the config-free contract holds; only no-arg adapters gain coverage).
    """
    caps: list[dict] = []
    seen: set[str] = set()
    for _name, member in inspect.getmembers(cls):
        descriptor = getattr(member, "__chp_descriptor__", None)
        cid = getattr(descriptor, "id", None)
        if cid and cid not in seen:
            seen.add(cid)
            caps.append({"id": cid, "description": (descriptor.description or "").strip()})
    if not caps:
        try:
            for hosted in cls().capabilities():          # dynamic-capabilities() adapters
                descriptor = getattr(hosted, "descriptor", None)
                cid = getattr(descriptor, "id", None)
                if cid and cid not in seen:
                    seen.add(cid)
                    caps.append({"id": cid,
                                 "description": (getattr(descriptor, "description", "") or "").strip()})
        except Exception:
            pass  # needs config (or any error) -> report capless, config-free, unchanged
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
