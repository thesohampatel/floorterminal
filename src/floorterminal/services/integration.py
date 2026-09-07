"""Application-facing wrapper for the external integration definition."""

from ..integration import ConfiguredIntegration
from .provider import ProviderInfo


class ExternalIntegration(ConfiguredIntegration):
    def __init__(self, config=None, logger=None, transport=None, definition=None):
        super().__init__(config, logger, transport, definition)
        capabilities = self.definition.capabilities
        self.INFO = ProviderInfo(
            "external",
            self.definition.display_name,
            "Credential in connector.json",
            bool(capabilities.get("asset_status")),
            bool(capabilities.get("messaging")),
            bool(capabilities.get("team_directory")),
            bool(capabilities.get("response_records")),
            bool(capabilities.get("response_record_status")),
            bool(capabilities.get("response_record_comments")),
            bool(capabilities.get("response_record_assignments")),
        )
