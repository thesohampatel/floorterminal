"""Stable application service boundary."""

from .integration import ExternalIntegration
from .provider import (
    MaintenanceProvider,
    NoIntegrationProvider,
    ProviderInfo,
)

__all__ = [
    "ExternalIntegration",
    "MaintenanceProvider",
    "NoIntegrationProvider",
    "ProviderInfo",
]
