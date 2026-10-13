#!/usr/bin/env python3
"""Serve installed chp-adapter-* capabilities as a governed CHP host over HTTP.

    pip install chp-server chp-adapter-safety chp-adapter-audit   # + any chp-adapter-*
    python serve_adapters.py                 # serve ALL installed adapters
    python serve_adapters.py safety audit     # serve only these
    python serve_adapters.py --list           # list installed adapters, exit
    python serve_adapters.py --check          # compose + report, don't block (for CI/tests)

Stands entirely on the PUBLIC stack — chp-server + chp-core + the adapters — with no
private-product dependency. Every call is admission-gated, executed, and recorded as a
signed, replayable evidence chain.
"""
from __future__ import annotations
import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="serve_adapters", description=__doc__)
    ap.add_argument("adapters", nargs="*", help="adapter names to serve (default: all installed)")
    ap.add_argument("--host-id", default="chp-host")
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--store", default="chp-host.sqlite")
    ap.add_argument("--list", action="store_true", help="list installed adapters and exit")
    ap.add_argument("--check", action="store_true", help="compose + report, then exit (no serve)")
    args = ap.parse_args(argv)

    from chp_core.adapters import discover_adapters
    from chp_server import CapabilityServer

    available = discover_adapters()  # {name: AdapterClass} for installed chp.adapters entry points
    if args.list:
        for name in sorted(available):
            print(name)
        return 0
    if not available:
        print("no chp-adapter-* installed — e.g. pip install chp-adapter-safety chp-adapter-audit",
              file=sys.stderr)
        return 1

    names = args.adapters or sorted(available)
    app = CapabilityServer(args.host_id, store=args.store)
    served: list[str] = []
    skipped: list[tuple[str, str]] = []
    for name in names:
        cls = available.get(name)
        if cls is None:
            skipped.append((name, "not installed")); continue
        try:
            app.compose(cls())  # no-arg: adapters needing config/secrets skip honestly
            served.append(name)
        except Exception as e:  # noqa: BLE001 — honest skip, never a silent half-serve
            skipped.append((name, f"needs config ({type(e).__name__})"))

    print(f"composed {len(served)} adapter(s): {', '.join(served) or '(none)'}")
    for name, why in skipped:
        print(f"  skipped {name}: {why}", file=sys.stderr)
    if not served:
        print("no adapters composed — nothing to serve", file=sys.stderr)
        return 1
    if args.check:
        return 0
    app.run(port=args.port, bind=args.bind)  # blocking; prints its own URL + curl banner
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
