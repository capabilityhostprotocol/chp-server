"""chp-server — independently installable reference CHP server.

Assembly only: protocol semantics live in chp-core; domain behavior attaches
through the `chp_server.ports` entry-point group. The only mandatory CHP
dependency is chp-core (DEC-SRV-001) — importing this package must never pull
an optional CHP package (PKG-009; enforced by tests/test_import_purity.py).
"""

from .config import ServerConfig
from .features import FEATURES, FeatureDescriptor, FeatureRegistry
from .introduction import (
    EntryPointIntroductionPort,
    IntroductionCoordinator,
    RemoteChpIntroductionSource,
    SourceTrustPolicy,
)
from .local import ExistingHostPort, LocalArtifactPort, LocalStandalonePorts
from .resolver import DirectoryResolutionPort, advertisement_batch
from .ports import ENTRY_POINT_GROUP, PORT_ROLES, Attachment, AttachmentRegistry
from .profiles import CONFORMANCE_MANIFEST, PROFILES, validate_profile
from .server import Server, ServerInstanceIdentity, ServerStatus
from .app import CapabilityServer

# Replay / ReplayEvent (the typed /replay view) live in chp_server.replay, not the
# top-level namespace — API-008 keeps the public surface small and curated. Advanced
# callers use `from chp_server.replay import Replay`; the CLI imports it directly.

__all__ = [
    "CapabilityServer",
    "Attachment",
    "AttachmentRegistry",
    "CONFORMANCE_MANIFEST",
    "ENTRY_POINT_GROUP",
    "EntryPointIntroductionPort",
    "ExistingHostPort",
    "IntroductionCoordinator",
    "SourceTrustPolicy",
    "DirectoryResolutionPort",
    "advertisement_batch",
    "LocalArtifactPort",
    "FEATURES",
    "FeatureDescriptor",
    "FeatureRegistry",
    "LocalStandalonePorts",
    "PORT_ROLES",
    "PROFILES",
    "RemoteChpIntroductionSource",
    "Server",
    "ServerConfig",
    "ServerInstanceIdentity",
    "ServerStatus",
    "validate_profile",
]
