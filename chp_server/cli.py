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

    describe = sub.add_parser("describe", help="Print Server.Describe for a config without serving.")
    describe.add_argument("--config", default=None, metavar="FILE")
    describe.add_argument("--profile", default=None)

    args = parser.parse_args(argv)
    from .config import ServerConfig
    from .server import Server

    try:
        config = ServerConfig.from_sources(
            config_file=args.config, bind=getattr(args, "bind", None),
            port=getattr(args, "port", None), profile=args.profile,
            store=getattr(args, "store", None))
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    server = Server(config)
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
