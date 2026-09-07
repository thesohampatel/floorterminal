"""Single vendor-neutral external integration contract and runtime."""

from .definition import (
    CONNECTOR_FILE,
    DefinitionError,
    IntegrationDefinition,
    write_connector,
)
from .discovery import (
    ConnectorCandidate,
    ConnectorInventory,
    ConnectorTestResult,
    discover_connectors,
    select_connector,
    test_connector,
)
from .runtime import IntegrationError, PreparedRequest, TransportResponse
from .template import basic_diagnostic_connector
from .workflow import ConfiguredIntegration

__all__ = [
    "CONNECTOR_FILE",
    "ConfiguredIntegration",
    "ConnectorCandidate",
    "ConnectorInventory",
    "ConnectorTestResult",
    "DefinitionError",
    "IntegrationDefinition",
    "IntegrationError",
    "PreparedRequest",
    "TransportResponse",
    "basic_diagnostic_connector",
    "discover_connectors",
    "select_connector",
    "test_connector",
    "write_connector",
]
