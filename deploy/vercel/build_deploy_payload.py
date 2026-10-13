"""Build the ``chp.adapters.vercel.trigger_deploy`` FILES payload from this template dir.

The governed Axis-2 path: this turns the local CHP-server-on-Vercel template into an inline
Vercel ``files`` bundle so CHP Home can deploy it through the mesh vercel adapter
(``home_invoke("<node>", "chp.adapters.vercel.trigger_deploy", <payload>)``) — no git repo needed.

    python build_deploy_payload.py --name chp-vercel --project chp-vercel > payload.json

Then (governed): home_invoke that payload on a node carrying chp-adapter-vercel >= 0.58.0.
"""
from __future__ import annotations

import argparse
import base64
import json
import os

# Files Vercel needs to build + run the function. Everything else (tests, caches, docs,
# this builder) is excluded so the deployment is exactly the runtime. app.py is Vercel's
# canonical FastAPI entrypoint (auto-detected); no vercel.json / framework override needed.
_INCLUDE = ["api/index.py", "vercel.json", "requirements.txt"]


def build_files(root: str) -> list[dict]:
    files: list[dict] = []
    for rel in _INCLUDE:
        path = os.path.join(root, rel)
        with open(path, "rb") as fh:
            data = base64.b64encode(fh.read()).decode("ascii")
        files.append({"file": rel, "data": data, "encoding": "base64"})
    return files


def build_payload(root: str, name: str, project: str | None = None,
                  target: str | None = None) -> dict:
    payload: dict = {
        "name": name,
        "files": build_files(root),
        # framework:null is REQUIRED for a non-git files deploy — it tells Vercel "no framework
        # preset, build the api/*.py functions" (requirements.txt drives the Python runtime).
        # Without it, framework auto-detection fails instantly (observed 2s config-stage ERROR).
        "project_settings": {"framework": None},
    }
    # Only link to a project when one is given — for a brand-new host, omit it so Vercel
    # creates the project from `name` (passing a non-existent project id errors).
    if project:
        payload["project"] = project
    if target:
        payload["target"] = target
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the vercel trigger_deploy files payload.")
    ap.add_argument("--name", default="chp-vercel", help="Deployment name.")
    ap.add_argument("--project", default=None,
                    help="Existing Vercel project id/name to deploy into; omit for a new host "
                         "(Vercel creates the project from --name).")
    ap.add_argument("--target", default=None, choices=[None, "production", "preview"],
                    help="Omit for a preview deployment.")
    ap.add_argument("--root", default=os.path.dirname(os.path.abspath(__file__)),
                    help="Template root (defaults to this file's directory).")
    args = ap.parse_args()
    print(json.dumps(build_payload(args.root, args.name, args.project, args.target), indent=2))


if __name__ == "__main__":
    main()
