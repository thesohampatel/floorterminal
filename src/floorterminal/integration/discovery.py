"""Safe discovery and selection of data-only connector files."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from ..core.config import write_private
from ..core.paths import RUNTIME_ROOT
from .definition import DefinitionError, IntegrationDefinition
from .runtime import IntegrationClient, IntegrationError

SELECTION_FILE = RUNTIME_ROOT / ".active_connector"
PATTERNS = (
    "connector.json",
    "*.connector.json",
    "*_connector.json",
    "*-connector.json",
    "connector-*.json",
    "connector_*.json",
)
MAX_CONNECTORS = 32


@dataclass(frozen=True)
class ConnectorCandidate:
    path: Path
    definition: IntegrationDefinition | None = None
    error: str = ""

    @property
    def valid(self):
        return self.definition is not None

    @property
    def ready(self):
        if not self.definition or not self.definition.enabled:
            return False
        required = self.definition.data["authentication"].get(
            "required_credentials", []
        )
        return all(self.definition.credentials.get(key, "").strip() for key in required)

    @property
    def status(self):
        if self.error:
            return "ERROR"
        return "READY" if self.ready else "DISABLED / INCOMPLETE"


@dataclass(frozen=True)
class ConnectorInventory:
    candidates: tuple[ConnectorCandidate, ...]
    active: ConnectorCandidate | None


@dataclass(frozen=True)
class ConnectorTestResult:
    success: bool
    message: str
    operation_id: str = ""
    duration_ms: int = 0


def _candidate_paths(root):
    root = Path(root).resolve()
    found = set()
    for pattern in PATTERNS:
        for path in root.glob(pattern):
            if path.is_file() and not path.name.endswith(".tmp"):
                resolved = path.resolve()
                if resolved.parent == root:
                    found.add(resolved)
    return sorted(
        found, key=lambda path: (path.name != "connector.json", path.name.casefold())
    )[:MAX_CONNECTORS]


def discover_connectors(root=None, selection_file=None):
    root = Path(root or RUNTIME_ROOT).resolve()
    selection_file = Path(selection_file or (root / SELECTION_FILE.name))
    candidates = []
    for path in _candidate_paths(root):
        try:
            candidates.append(ConnectorCandidate(path, IntegrationDefinition(path)))
        except (DefinitionError, OSError) as exc:
            candidates.append(ConnectorCandidate(path, error=str(exc)))
    selected_name = ""
    try:
        selected_name = selection_file.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    valid = [item for item in candidates if item.valid]
    ready = [item for item in valid if item.ready]
    active = next((item for item in ready if item.path.name == selected_name), None)
    if active is None:
        active = next(
            (item for item in ready if item.path.name == "connector.json"), None
        )
    if active is None and ready:
        active = ready[0]
    if active is None:
        active = next((item for item in valid if item.path.name == selected_name), None)
    if active is None:
        active = next(
            (item for item in valid if item.path.name == "connector.json"), None
        )
    if active is None and valid:
        active = valid[0]
    return ConnectorInventory(tuple(candidates), active)


def select_connector(filename, root=None, selection_file=None):
    root = Path(root or RUNTIME_ROOT).resolve()
    selection_file = Path(selection_file or (root / SELECTION_FILE.name))
    inventory = discover_connectors(root, selection_file)
    candidate = next(
        (item for item in inventory.candidates if item.path.name == filename), None
    )
    if not candidate or not candidate.valid:
        raise DefinitionError("Select a valid detected connector file")
    write_private(selection_file, (candidate.path.name + "\n").encode("utf-8"))
    return discover_connectors(root, selection_file)


def test_connector(candidate, config=None, logger=None, transport=None):
    """Run local validation plus at most one explicitly safe GET request."""
    if not candidate or not candidate.valid:
        return ConnectorTestResult(
            False, candidate.error if candidate else "No connector selected"
        )
    if not candidate.ready:
        return ConnectorTestResult(
            False, "Connector is disabled or required credentials are missing"
        )
    definition = candidate.definition
    diagnostics = definition.data.get("diagnostics", {})
    operation_id = diagnostics.get("test_operation", "")
    if not operation_id:
        preferred = ("list_users", "list_teams", "list_conversations")
        mappings = definition.workflow.get("operations", {})
        operation_id = next(
            (
                mappings[name]
                for name in preferred
                if mappings.get(name)
                and definition.operation(mappings[name]).method == "GET"
            ),
            "",
        )
    if not operation_id:
        return ConnectorTestResult(
            True, "Local validation passed; no safe GET diagnostic is configured"
        )
    operation = definition.operation(operation_id)
    if operation.method != "GET":
        return ConnectorTestResult(
            False, "Diagnostic was blocked because it is not read-only"
        )
    started = time.monotonic()
    try:
        IntegrationClient(definition, config or {}, logger, transport).execute(
            operation_id, query=diagnostics.get("query", {})
        )
    except (DefinitionError, IntegrationError) as exc:
        return ConnectorTestResult(
            False,
            f"Online test failed: {exc}",
            operation_id,
            round((time.monotonic() - started) * 1000),
        )
    return ConnectorTestResult(
        True,
        "Local validation, HTTPS, authentication, permission and response checks passed",
        operation_id,
        round((time.monotonic() - started) * 1000),
    )
