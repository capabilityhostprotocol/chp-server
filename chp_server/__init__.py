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
)
from .local import ExistingHostPort, LocalArtifactPort, LocalStandalonePorts
from .ports import ENTRY_POINT_GROUP, PORT_ROLES, Attachment, AttachmentRegistry
from .profiles import CONFORMANCE_MANIFEST, PROFILES, validate_profile
from .server import Server, ServerInstanceIdentity, ServerStatus

__all__ = [
    "Attachment",
    "AttachmentRegistry",
    "CONFORMANCE_MANIFEST",
    "ENTRY_POINT_GROUP",
    "EntryPointIntroductionPort",
    "ExistingHostPort",
    "IntroductionCoordinator",
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
