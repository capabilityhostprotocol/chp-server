"""ServerConfig — deterministic precedence + generations (doc 40).

Precedence: built-in defaults -> config file (JSON) -> environment -> explicit
programmatic overrides. Effective configuration is inspectable with secrets
redacted; unknown fields fail validation.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from chp_core.environment import current_environment, validate_environment

_ENV_PREFIX = "CHP_SERVER_"
_SECRET_FIELDS = ("tls_keyfile",)


@dataclass
class ServerConfig:
    bind: str = "127.0.0.1"
    port: int = 8770
    profile: str = "protocol-only"
    environment: str = field(default_factory=current_environment)
    host_id: str = "chp-server"
    store: str | None = None            # evidence store path; None = chp-core default
    tls_certfile: str | None = None
    tls_keyfile: str | None = None
    tls_cafile: str | None = None
    # attachments: {entry_point_name: {kwargs}} — Phase B config (doc 40 §3);
    # only listed attachments are loaded even when more are installed.
    attachments: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_environment(self.environment)
        from .profiles import PROFILES
        if self.profile not in PROFILES:
            raise ValueError(f"unknown profile {self.profile!r}; valid: {sorted(PROFILES)}")

    @classmethod
    def from_sources(cls, config_file: str | Path | None = None,
                     env: dict[str, str] | None = None, **overrides: Any) -> "ServerConfig":
        env = os.environ if env is None else env
        known = {f.name for f in fields(cls)}
        merged: dict[str, Any] = {}
        if config_file:
            data = json.loads(Path(config_file).read_text())
            unknown = set(data) - known
            if unknown:  # unknown fields fail closed (doc 40 §7)
                raise ValueError(f"unknown configuration fields: {sorted(unknown)}")
            merged.update(data)
        for f in fields(cls):
            key = _ENV_PREFIX + f.name.upper()
            if key in env:
                raw = env[key]
                merged[f.name] = int(raw) if f.type == "int" else raw
        merged.update({k: v for k, v in overrides.items() if v is not None})
        unknown = set(merged) - known
        if unknown:
            raise ValueError(f"unknown configuration fields: {sorted(unknown)}")
        return cls(**merged)

    def redacted(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        for k in _SECRET_FIELDS:
            if d.get(k):
                d[k] = "<redacted>"
        return d
