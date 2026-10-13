"""chp-server CLI — `chp serve` (via the chp-core shim) lands here."""

from __future__ import annotations

import argparse
import json
import sys


# tier → adapters to serve once provisioned (cumulative); mirrors deploy/guided-install.sh.
_TIER_ADAPTERS = {"node": [], "containment": ["safety", "audit"], "assurance": ["safety", "audit"]}


def _onboard(args: argparse.Namespace) -> int:
    """pip-install onboarding: provision the chosen tier's system prerequisites through the
    governed, evidenced capability `chp.adapters.host.bootstrap` (recorded as signed, chained
    CHP ExecutionEvidence — no hand-rolled ledger), then bring up the governed host serving the
    tier's adapters. Requires chp-adapter-host (install it: pip install chp-adapter-host)."""
    import os
    import time

    try:
        from chp_adapter_host import HostAdapter
        from chp_adapter_host import bootstrap as _bs
    except ModuleNotFoundError:
        print("ERROR: onboard provisions through the governed host-bootstrap capability, which\n"
              "       lives in chp-adapter-host. Install it first:\n"
              "         pip install chp-adapter-host", file=sys.stderr)
        return 1

    # --plan: pure, cross-OS feasibility preview — no host, no evidence, no serve.
    if getattr(args, "plan", False):
        try:
            print(_bs.render_plan(args.tier, _bs.detect_host(), with_inference=bool(args.inference)))
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        return 0

    from chp_core.adapters import discover_adapters
    from chp_server import CapabilityServer

    store = args.store or os.path.join(os.path.expanduser("~/.chp-host"), "onboard.sqlite")
    os.makedirs(os.path.dirname(store) or ".", exist_ok=True)
    app = CapabilityServer("chp-onboard", store=store)
    app.compose(HostAdapter())  # the governed bootstrap capability

    # Compose the tier's adapters (+ any the operator named, + ollama-backed local_llm for
    # --inference), honest-skip anything absent or needing config — never a silent half-serve.
    available = discover_adapters()
    want = list(args.adapters if args.adapters is not None else _TIER_ADAPTERS.get(args.tier, []))
    if args.inference and "local_llm" not in want:
        want.append("local_llm")
    served, skipped = [], []
    for name in want:
        cls = available.get(name)
        if cls is None:
            skipped.append((name, "not installed")); continue
        try:
            app.compose(cls()); served.append(name)
        except Exception as exc:  # noqa: BLE001 — honest skip
            skipped.append((name, f"needs config ({type(exc).__name__})"))

    # --- the governed, EVIDENCED provision step (this is the CHP-evidence record) ---
    corr = f"onboard-{args.tier}-{int(time.time())}"
    print(f"==> Provisioning tier {args.tier!r}"
          + (" +inference" if args.inference else "")
          + (" (dry-run)" if args.dry_run else "")
          + " — governed + evidenced via chp.adapters.host.bootstrap …")
    result = app.host.invoke(
        "chp.adapters.host.bootstrap",
        {"tier": args.tier, "inference": bool(args.inference), "dry_run": bool(args.dry_run)},
        correlation_id=corr)
    rec = getattr(result, "data", {}) or {}
    outcome = rec.get("outcome", "unknown")
    print(f"    outcome: {outcome}   (evidence correlation_id={corr}, store={store})")
    for s in rec.get("steps", []):
        print(f"      [{'ok ' if s.get('ok') else 'FAIL'}] {s.get('name')}  (exit {s.get('exit_code')})")
    for item in rec.get("unsatisfiable", []):
        print(f"      (honest) cannot provide {item.get('name')}: {item.get('reason')}")
    still = (rec.get("verified_after") or {}).get("still_missing") or []
    if still:
        print(f"    still missing after install: {', '.join(still)}", file=sys.stderr)
    if outcome in ("failed", "partial"):
        print(f"    note: provision was {outcome!r} — the evidence records exactly what happened; "
              "inspect it with  chp-server replay.", file=sys.stderr)

    print(f"==> Host composed {len(served) + 1} adapter(s): host"
          + (", " + ", ".join(served) if served else " (tier adds none)"))
    for name, why in skipped:
        print(f"      skipped {name}: {why}", file=sys.stderr)

    if args.no_serve or args.dry_run:
        print(f"==> Not serving (--{'no-serve' if args.no_serve else 'dry-run'}). "
              f"Onboarding evidence recorded at {store}")
        return 0
    print(f"==> Serving on http://{args.bind}:{args.port} — inspect the install evidence:")
    print(f"      curl -s http://{args.bind}:{args.port}/replay/{corr} | chp-server replay")
    app.run(port=args.port, bind=args.bind)  # blocking
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chp-server",
        description="Reference CHP server: chp-core protocol surface + optional attachments.")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start the server (blocking).")
    serve.add_argument("--bind", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--profile", default=None)
    serve.add_argument("--config", default=None, metavar="FILE", help="JSON config file")
    serve.add_argument("--store", default=None, metavar="PATH", help="Evidence store path")
    serve.add_argument("--example", action="store_true",
                       help="Attach a few sample capabilities (greet.hello, math.add, "
                            "time.now) so the server is live and curl-able on first run.")

    describe = sub.add_parser("describe", help="Print Server.Describe for a config without serving.")
    describe.add_argument("--config", default=None, metavar="FILE")
    describe.add_argument("--profile", default=None)

    new = sub.add_parser("new", help="Scaffold a runnable starter capability server.")
    new.add_argument("name", help="Starter file to create, e.g. 'mycaps' or 'mycaps.py'.")
    new.add_argument("--force", action="store_true", help="Overwrite if the file exists.")

    adapters = sub.add_parser(
        "adapters", help="List installed chp-adapter-* capability sets you can compose().")
    adapters.add_argument("--verbose", action="store_true",
                          help="Show each capability id + description.")
    adapters.add_argument("--json", action="store_true", help="Emit the catalog as JSON.")

    replay = sub.add_parser(
        "replay", help="Pretty-print a GET /replay evidence chain (JSON from stdin or --file).")
    replay.add_argument("--file", default=None, metavar="PATH",
                        help="Read the /replay JSON from a file instead of stdin.")

    onboard = sub.add_parser(
        "onboard",
        help="Provision this host's system prerequisites for a tier (governed + evidenced via "
             "chp.adapters.host.bootstrap), then serve. The pip-install onboarding path.")
    onboard.add_argument("--tier", choices=["node", "containment", "assurance"], default="node",
                         help="How deep to provision (cumulative: node ⊂ containment ⊂ assurance). "
                              "Default: node.")
    onboard.add_argument("--inference", action="store_true",
                         help="Also plan a sovereign LLM backend (ollama).")
    onboard.add_argument("--plan", action="store_true",
                         help="Pure feasibility preview for this device — no install, no serve, no "
                              "evidence (cross-OS; honestly skips what the hardware/OS can't provide).")
    onboard.add_argument("--dry-run", action="store_true",
                         help="Plan only — install nothing; still records an evidenced plan.")
    onboard.add_argument("--no-serve", action="store_true",
                         help="Provision + record evidence, then exit without serving.")
    onboard.add_argument("--adapters", nargs="*", default=None, metavar="NAME",
                         help="Adapters to serve (default: the tier's set + --inference's).")
    onboard.add_argument("--port", type=int, default=8800)
    onboard.add_argument("--bind", default="127.0.0.1")
    onboard.add_argument("--store", default=None, metavar="PATH",
                         help="Evidence store path (default ~/.chp-host/onboard.sqlite).")

    args = parser.parse_args(argv)

    if args.command == "onboard":
        return _onboard(args)

    if args.command == "replay":
        from .replay import Replay
        if args.file:
            try:
                raw = open(args.file).read()
            except OSError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1
        elif sys.stdin.isatty():
            # No --file and an interactive stdin: NEVER block on stdin.read() (that hung a
            # CLI invocation indefinitely). Show usage and exit instead.
            print("chp-server replay: pipe a /replay response, or pass --file. e.g.\n"
                  "  curl -s http://127.0.0.1:8800/replay/<correlation_id> | chp-server replay\n"
                  "  chp-server replay --file replay.json", file=sys.stderr)
            return 2
        else:
            raw = sys.stdin.read()
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"ERROR: input is not valid JSON ({exc}). Pipe a /replay response, e.g.:\n"
                  "  curl -s http://127.0.0.1:8800/replay/<correlation_id> | chp-server replay",
                  file=sys.stderr)
            return 1
        print(Replay.from_wire(doc).render())
        return 0

    if args.command == "adapters":
        from ._catalog import adapter_catalog
        catalog = adapter_catalog()
        if getattr(args, "json", False):
            print(json.dumps(catalog, indent=2))
            return 0
        if not catalog:
            print("No chp-adapter-* packages installed in this environment.\n"
                  "Install some (e.g. pip install chp-adapter-filesystem), then compose them:\n"
                  "  app.compose(FilesystemAdapter(...))")
            return 0
        total = sum(len(a["capabilities"]) for a in catalog)
        print(f"{len(catalog)} adapters installed ({total} capabilities) — "
              "compose with app.compose(AdapterClass(...)):\n")
        for a in catalog:
            print(f"  {a['name']:24} {len(a['capabilities']):>3} caps")
            if getattr(args, "verbose", False):
                for c in a["capabilities"]:
                    print(f"       {c['id']}  —  {c['description'][:68]}")
        return 0

    if args.command == "new":
        from ._scaffold import write_starter
        try:
            path = write_starter(args.name, force=args.force)
        except OSError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(f"Created {path} — run it with:  python {path}")
        return 0

    from .config import ServerConfig
    from .server import Server

    # --example needs a host to attach to; default it into the `host` profile
    # unless the caller chose one explicitly.
    example = getattr(args, "example", False)
    profile = args.profile or ("host" if example else None)

    try:
        config = ServerConfig.from_sources(
            config_file=args.config, bind=getattr(args, "bind", None),
            port=getattr(args, "port", None), profile=profile,
            store=getattr(args, "store", None))
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    server = Server(config)

    example_dir = None
    if example:
        import os
        import tempfile
        from ._example import build_example_host
        from .local import ExistingHostPort
        example_dir = tempfile.mkdtemp(prefix="chp-example-")
        server.attach(ExistingHostPort(
            build_example_host(os.path.join(example_dir, "example.sqlite"))))

    if args.command == "describe":
        print(json.dumps(server.describe(), indent=2))
        return 0

    try:
        server.start()
    except RuntimeError as exc:  # fail-closed profile validation
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"chp-server {server.identity.instance_id} serving profile "
          f"{config.profile!r} at http://{config.bind}:{server.port}")
    print("Routes: GET /health /ready /server /host /capabilities, POST /invoke")
    if example:
        base = f"http://{config.bind}:{server.port}"
        print("\nSample capabilities attached — try:")
        print(f"  curl {base}/capabilities.txt")
        print(f"  curl {base}/invoke -H 'Content-Type: application/json' \\")
        print("       -d '{\"capability_id\": \"greet.hello\", \"payload\": {\"name\": \"CHP\"}}'")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    print("\nStopped chp-server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
