"""chp-server CLI — `chp serve` (via the chp-core shim) lands here."""

from __future__ import annotations

import argparse
import json
import sys


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

    args = parser.parse_args(argv)

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
