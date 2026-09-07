"""Vendor-neutral maintenance-system provider contract and registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ProviderInfo:
    """Stable identity and UI labels supplied by an integration adapter."""

    provider_id: str
    display_name: str
    credential_label: str = "API token"
    supports_asset_status: bool = True
    supports_messaging: bool = True
    supports_team_directory: bool = True
    supports_response_records: bool = True
    supports_response_record_status: bool = True
    supports_response_record_comments: bool = True
    supports_response_record_assignments: bool = True


class NoIntegrationProvider:
    """Safe terminal state used until connector.json is complete and enabled."""

    INFO = ProviderInfo(
        provider_id="none",
        display_name="Integration required",
        credential_label="Integration credential",
        supports_asset_status=False,
        supports_messaging=False,
        supports_team_directory=False,
        supports_response_records=False,
        supports_response_record_status=False,
        supports_response_record_comments=False,
        supports_response_record_assignments=False,
    )
    limit = remaining = reset = window_resets_at = None
    session_used = 0

    def __init__(self, config=None, logger=None):
        self.config = config or {}
        self.logger = logger

    connected = False
    identity_name = ""
    app_window_used = 0

    @classmethod
    def validate_configuration(cls, config):
        return None

    @classmethod
    def validate_credential(cls, credential):
        return None

    def reconfigure(self, credential, organization_id, config, logger=None):
        self.config = config
        self.logger = logger

    def _missing(self, *args, **kwargs):
        raise RuntimeError("Configure and enable connector.json in Settings")

    load_identity = lambda self: ""
    directory = lambda self: {"teams": [], "conversations": []}
    resolve_name = team_members = create_response_record = set_response_record_status = (
        assign_participants
    ) = add_response_record_comment = send_message = set_asset_status = _missing


@runtime_checkable
class MaintenanceProvider(Protocol):
    """Operations required by the downtime workflow, independent of vendor APIs."""

    INFO: ProviderInfo
    config: dict
    logger: object
    limit: int | None
    remaining: int | None

    @property
    def connected(self) -> bool: ...

    @property
    def identity_name(self) -> str: ...

    @property
    def app_window_used(self) -> int: ...

    def reconfigure(
        self, credential: str | None, organization_id: str, config: dict, logger=None
    ) -> None: ...
    def load_identity(self) -> str: ...
    def directory(self) -> dict: ...
    def resolve_name(self, resource: str, name: str) -> int: ...
    def team_members(self, team_id: int) -> list: ...
    def create_response_record(
        self,
        title,
        description,
        team_id,
        priority="HIGH",
        work_type=None,
        participant_ids=None,
        idempotency_key=None,
    ) -> dict: ...
    def set_response_record_status(self, response_record_id, status) -> dict: ...
    def assign_participants(self, response_record_id, team_id, user_ids) -> dict: ...
    def add_response_record_comment(self, response_record_id, content) -> dict: ...
    def send_message(self, target_name, content) -> dict: ...
    def set_asset_status(
        self,
        status,
        downtime_type=None,
        description=None,
        started_at=None,
        idempotency_key=None,
    ) -> dict: ...
