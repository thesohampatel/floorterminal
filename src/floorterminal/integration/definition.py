"""Validated vendor-neutral integration definition loaded beside the application."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ..core.config import write_private
from ..core.paths import RUNTIME_ROOT

CONNECTOR_FILE = RUNTIME_ROOT / "connector.json"


class DefinitionError(ValueError):
    pass


@dataclass(frozen=True)
class OperationDefinition:
    operation_id: str
    method: str
    path: str
    success_codes: tuple[int, ...]
    retry_codes: tuple[int, ...]
    retry_safe: bool
    retry_network_errors: bool
    retry_max_attempts: int
    retry_backoff_seconds: float
    raw: dict


class IntegrationDefinition:
    """Load one complete integration contract without a vendor registry."""

    RESERVED_HEADERS = frozenset(
        {
            "connection",
            "content-length",
            "host",
            "proxy-authorization",
            "te",
            "trailer",
            "transfer-encoding",
            "upgrade",
        }
    )

    def __init__(self, path=None):
        self.path = Path(path or CONNECTOR_FILE)
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise DefinitionError(f"Cannot read {self.path.name}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise DefinitionError(
                f"Invalid {self.path.name} at line {exc.lineno}, column {exc.colno}"
            ) from exc
        self._validate()

    @staticmethod
    def _validate_idempotency(data, operation, label):
        idempotency = operation.get("idempotency")
        if not isinstance(idempotency, dict):
            raise DefinitionError(
                f"{label} requires a remotely enforced idempotency definition"
            )
        location = idempotency.get("location")
        name = idempotency.get("name")
        if location not in {"header", "query", "body"}:
            raise DefinitionError(
                f"{label} idempotency location must be header, query, or body"
            )
        if not isinstance(name, str) or not name.strip():
            raise DefinitionError(f"{label} idempotency name cannot be empty")
        if set(idempotency) - {"location", "name", "remote_guarantee"}:
            raise DefinitionError(f"{label} idempotency contains unsupported fields")
        if idempotency.get("remote_guarantee") is not True:
            raise DefinitionError(
                f"{label} idempotency must declare remote_guarantee true"
            )
        if location == "header" and not re.fullmatch(r"[A-Za-z0-9-]+", name):
            raise DefinitionError(f"{label} idempotency header name is invalid")
        if location == "header" and name.casefold() in {
            "authorization",
            "content-length",
            "content-type",
            "host",
        }:
            raise DefinitionError(f"{label} idempotency header name is reserved")
        configured_headers = {
            str(value).casefold()
            for value in (
                set(data["authentication"].get("headers", {}))
                | set(operation.get("headers", {}))
            )
        }
        if location == "header" and name.casefold() in configured_headers:
            raise DefinitionError(
                f"{label} idempotency header conflicts with another header"
            )
        if location == "query" and name not in operation.get("query_parameters", []):
            raise DefinitionError(
                f"{label} idempotency query name must be an allowed query parameter"
            )
        if location == "body" and not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", name
        ):
            raise DefinitionError(f"{label} idempotency body path is invalid")

    @classmethod
    def _validate_header(cls, name, template, label):
        name = str(name)
        template = str(template)
        if not re.fullmatch(r"[A-Za-z0-9-]+", name):
            raise DefinitionError(f"{label} has an invalid header name")
        if name.casefold() in cls.RESERVED_HEADERS:
            raise DefinitionError(f"{label} cannot set reserved header {name}")
        if "\r" in template or "\n" in template:
            raise DefinitionError(f"{label} header values cannot contain line breaks")

    def _validate(self):
        data = self.data
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise DefinitionError("connector.json must use schema_version 1")
        for key in (
            "contract",
            "identity",
            "connection",
            "credentials",
            "authentication",
            "operations",
            "workflow",
            "capabilities",
        ):
            if not isinstance(data.get(key), dict):
                raise DefinitionError(f"connector.json section {key} must be an object")
        if not str(data["identity"].get("display_name", "")).strip():
            raise DefinitionError("Connector display name cannot be empty")
        subject_id = data["identity"].get("authenticated_subject_id", "")
        if isinstance(subject_id, bool) or not isinstance(subject_id, (str, int)):
            raise DefinitionError(
                "Connector authenticated_subject_id must be text or a number"
            )
        if len(str(subject_id)) > 256:
            raise DefinitionError("Connector authenticated_subject_id is too long")
        if data["contract"].get("name") != "FloorTerminal External Connector":
            raise DefinitionError("connector.json has an unsupported contract name")
        if data["contract"].get("version") != "1.0":
            raise DefinitionError("connector.json has an unsupported contract version")
        protocol = str(data["connection"].get("protocol", "rest")).lower()
        if protocol not in {"rest", "rpc", "oslc", "odata"}:
            raise DefinitionError(
                "Connector protocol must be rest, rpc, oslc, or odata"
            )
        base = str(data["connection"].get("base_url", "")).strip()
        timeout = data["connection"].get("timeout_seconds")
        budget = data["connection"].get("requests_per_minute")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or not 3 <= timeout <= 120
        ):
            raise DefinitionError("Connector timeout_seconds must be 3 to 120")
        if (
            isinstance(budget, bool)
            or not isinstance(budget, int)
            or not 1 <= budget <= 10
        ):
            raise DefinitionError("Connector requests_per_minute must be 1 to 10")
        if data.get("enabled"):
            parsed = urlparse(base)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.query
                or parsed.fragment
            ):
                raise DefinitionError(
                    "Enabled integration base_url must be an HTTPS URL without credentials, query, or fragment"
                )
            allowed_hosts = data["connection"].get("allowed_hosts", [])
            if not isinstance(allowed_hosts, list) or any(
                not isinstance(host, str) or not host.strip() for host in allowed_hosts
            ):
                raise DefinitionError(
                    "Connector allowed_hosts must be a list of host names"
                )
            if allowed_hosts and parsed.hostname.casefold() not in {
                host.strip().casefold() for host in allowed_hosts
            }:
                raise DefinitionError("Connector base_url host is not in allowed_hosts")
        operations = data["operations"]
        diagnostics = data.get("diagnostics", {})
        if not isinstance(diagnostics, dict):
            raise DefinitionError("Connector diagnostics must be an object")
        test_operation = diagnostics.get("test_operation")
        if test_operation:
            if test_operation not in operations:
                raise DefinitionError("Connector diagnostic operation does not exist")
            if operations[test_operation].get("method") != "GET":
                raise DefinitionError("Connector diagnostic operation must use GET")
            test_query = diagnostics.get("query", {})
            if not isinstance(test_query, dict) or any(
                key not in operations[test_operation].get("query_parameters", [])
                for key in test_query
            ):
                raise DefinitionError("Connector diagnostic query is invalid")
        capability_names = {
            "response_records",
            "response_record_status",
            "response_record_comments",
            "response_record_assignments",
            "asset_status",
            "messaging",
            "team_directory",
        }
        missing_capabilities = sorted(capability_names - set(data["capabilities"]))
        if missing_capabilities:
            raise DefinitionError(
                "Connector capabilities are missing: " + ", ".join(missing_capabilities)
            )
        invalid_capabilities = sorted(
            name
            for name in capability_names
            if not isinstance(data["capabilities"].get(name), bool)
        )
        if invalid_capabilities:
            raise DefinitionError(
                "Connector capabilities must be true or false: "
                + ", ".join(invalid_capabilities)
            )
        workflow_operations = data["workflow"].get("operations")
        if not isinstance(workflow_operations, dict):
            raise DefinitionError("Integration workflow.operations must be an object")
        semantic = set()
        if str(subject_id).strip():
            semantic.add("load_user")
        if data["capabilities"].get("response_records"):
            semantic.add("create_response_record")
        if data["capabilities"].get("response_record_status"):
            semantic.add("update_response_record_status")
        if data["capabilities"].get("response_record_comments"):
            semantic.add("create_response_record_comment")
        if data["capabilities"].get("response_record_assignments"):
            semantic.add("update_response_record")
        if data["capabilities"].get("team_directory"):
            semantic.update({"list_users", "list_teams", "list_team_members"})
        if data["capabilities"].get("asset_status"):
            semantic.add("create_asset_status")
        if data["capabilities"].get("messaging"):
            semantic.update(
                {
                    "list_users",
                    "list_conversations",
                    "send_conversation_message",
                    "send_user_message",
                }
            )
        missing_semantic = sorted(semantic - set(workflow_operations))
        unknown_targets = sorted(
            str(workflow_operations[name])
            for name in semantic
            if name in workflow_operations
            and workflow_operations[name] not in operations
        )
        if missing_semantic:
            raise DefinitionError(
                "Integration workflow is missing: " + ", ".join(missing_semantic)
            )
        if unknown_targets:
            raise DefinitionError(
                "Integration workflow maps unknown operations: "
                + ", ".join(unknown_targets)
            )
        if data["capabilities"].get("response_records"):
            create_id = workflow_operations.get("create_response_record")
            create_operation = operations.get(create_id, {})
            self._validate_idempotency(data, create_operation, "Response-record creation")
        if data["capabilities"].get("asset_status"):
            create_id = workflow_operations.get("create_asset_status")
            create_operation = operations.get(create_id, {})
            self._validate_idempotency(data, create_operation, "Asset-status creation")
        for section in ("collections", "objects", "fields", "field_types", "values"):
            if not isinstance(data["workflow"].get(section), dict):
                raise DefinitionError(f"Connector workflow.{section} must be an object")
        allowed_field_types = {"string", "integer", "number", "boolean"}
        invalid_field_types = sorted(
            str(name)
            for name, kind in data["workflow"]["field_types"].items()
            if kind not in allowed_field_types
        )
        if invalid_field_types:
            raise DefinitionError(
                "Connector workflow.field_types contains invalid entries: "
                + ", ".join(invalid_field_types)
            )
        for operation_id, raw in operations.items():
            if not isinstance(raw, dict):
                raise DefinitionError(f"Operation {operation_id} must be an object")
            if not re.fullmatch(r"[a-z][a-z0-9_.-]*", operation_id):
                raise DefinitionError(f"Invalid operation ID: {operation_id}")
            if raw.get("method") not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                raise DefinitionError(f"Invalid method for {operation_id}")
            operation_path = str(raw.get("path", ""))
            if (
                not operation_path.startswith("/")
                or operation_path.startswith("//")
                or "?" in operation_path
            ):
                raise DefinitionError(f"Invalid path for {operation_id}")
            query_parameters = raw.get("query_parameters")
            query_aliases = raw.get("query_aliases", {})
            if not isinstance(query_parameters, list) or not isinstance(
                query_aliases, dict
            ):
                raise DefinitionError(f"Invalid query definition for {operation_id}")
            if any(value not in query_parameters for value in query_aliases.values()):
                raise DefinitionError(
                    f"Query alias for {operation_id} targets an unsupported parameter"
                )
            for mapping_name in ("static_query", "headers"):
                if not isinstance(raw.get(mapping_name, {}), dict):
                    raise DefinitionError(
                        f"Operation {operation_id} {mapping_name} must be an object"
                    )
            for header_name in raw.get("headers", {}):
                self._validate_header(
                    header_name,
                    raw["headers"][header_name],
                    f"Operation {operation_id}",
                )
            body = raw.get("body", {})
            if not isinstance(body, dict):
                raise DefinitionError(
                    f"Operation {operation_id} body must be an object"
                )
            if body.get("encoding", "json") not in {"json", "form", "none"}:
                raise DefinitionError(
                    f"Operation {operation_id} has invalid body encoding"
                )
            response_path = raw.get("response_body_path", "")
            if not isinstance(response_path, str):
                raise DefinitionError(
                    f"Operation {operation_id} response_body_path must be text"
                )
            codes = raw.get("success_codes")
            if (
                not isinstance(codes, list)
                or not codes
                or any(not isinstance(code, int) for code in codes)
            ):
                raise DefinitionError(f"Invalid success codes for {operation_id}")
            retry = raw.get("retry", {})
            if not isinstance(retry, dict):
                raise DefinitionError(f"Operation {operation_id} retry must be an object")
            unknown_retry = set(retry) - {
                "safe",
                "retry_on",
                "network_errors",
                "max_attempts",
                "backoff_seconds",
            }
            if unknown_retry:
                raise DefinitionError(
                    f"Operation {operation_id} retry contains unsupported fields"
                )
            if "safe" in retry and not isinstance(retry["safe"], bool):
                raise DefinitionError(
                    f"Operation {operation_id} retry.safe must be true or false"
                )
            if "network_errors" in retry and not isinstance(
                retry["network_errors"], bool
            ):
                raise DefinitionError(
                    f"Operation {operation_id} retry.network_errors must be true or false"
                )
            retry_codes = retry.get("retry_on", [])
            if not isinstance(retry_codes, list) or any(
                isinstance(code, bool)
                or not isinstance(code, int)
                or not 400 <= code <= 599
                for code in retry_codes
            ):
                raise DefinitionError(
                    f"Operation {operation_id} retry.retry_on must contain HTTP error codes"
                )
            attempts = retry.get("max_attempts", 1)
            if (
                isinstance(attempts, bool)
                or not isinstance(attempts, int)
                or not 1 <= attempts <= 3
            ):
                raise DefinitionError(
                    f"Operation {operation_id} retry.max_attempts must be 1 to 3"
                )
            backoff = retry.get("backoff_seconds", 0)
            if (
                isinstance(backoff, bool)
                or not isinstance(backoff, (int, float))
                or not 0 <= backoff <= 5
            ):
                raise DefinitionError(
                    f"Operation {operation_id} retry.backoff_seconds must be 0 to 5"
                )
            retry_requested = bool(retry_codes or retry.get("network_errors"))
            if retry_requested and retry.get("safe") is not True:
                raise DefinitionError(
                    f"Operation {operation_id} retries require retry.safe true"
                )
            if retry_requested and attempts < 2:
                raise DefinitionError(
                    f"Operation {operation_id} retries require max_attempts of at least 2"
                )
        if any(
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key))
            for key in data["credentials"]
        ):
            raise DefinitionError("Credential field names are invalid")
        authentication = data["authentication"]
        if authentication.get("type", "headers") not in {
            "headers",
            "api_key",
            "basic",
            "bearer",
            "custom",
        }:
            raise DefinitionError("Connector authentication type is unsupported")
        required_credentials = authentication.get("required_credentials", [])
        if not isinstance(required_credentials, list) or any(
            key not in data["credentials"] for key in required_credentials
        ):
            raise DefinitionError("Authentication required_credentials are invalid")
        headers = authentication.get("headers")
        if not isinstance(headers, dict):
            raise DefinitionError("Authentication headers must be an object")
        for section in ("query", "body", "derived_credentials"):
            if not isinstance(authentication.get(section, {}), dict):
                raise DefinitionError(f"Authentication {section} must be an object")
        derived = authentication.get("derived_credentials", {})
        if set(derived) & set(data["credentials"]):
            raise DefinitionError("Derived credential names must be unique")
        for name, item in derived.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name)) or not isinstance(
                item, dict
            ):
                raise DefinitionError("Derived credential definitions are invalid")
            if item.get("transform", "none") not in {"none", "base64", "urlencode"}:
                raise DefinitionError(
                    f"Derived credential {name} has an invalid transform"
                )
            if not isinstance(item.get("template", ""), str):
                raise DefinitionError(
                    f"Derived credential {name} template must be text"
                )
        variables = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
        known_variables = set(data["credentials"]) | set(derived)
        for name, template in headers.items():
            self._validate_header(name, template, "Authentication")
            if any(
                key not in known_variables for key in variables.findall(str(template))
            ):
                raise DefinitionError(
                    f"Authentication field {name} uses an unknown credential"
                )
        for section in ("query", "body"):
            for name, template in authentication.get(section, {}).items():
                if not str(name).strip() or any(
                    key not in known_variables
                    for key in variables.findall(str(template))
                ):
                    raise DefinitionError(
                        f"Authentication {section} field {name} is invalid"
                    )
        for operation_id, raw in operations.items():
            for name, template in raw.get("headers", {}).items():
                if any(
                    key not in known_variables
                    for key in variables.findall(str(template))
                ):
                    raise DefinitionError(
                        f"Operation {operation_id} header {name} uses an unknown credential"
                    )
        for item in derived.values():
            if any(
                key not in data["credentials"]
                for key in variables.findall(item.get("template", ""))
            ):
                raise DefinitionError(
                    "Derived credential uses an unknown source credential"
                )

    @property
    def enabled(self):
        return bool(self.data.get("enabled"))

    @property
    def display_name(self):
        return str(self.data["identity"]["display_name"]).strip()

    @property
    def credentials(self):
        return {
            str(k): str(v) for k, v in self.data["credentials"].items() if v is not None
        }

    @property
    def workflow(self):
        return self.data["workflow"]

    @property
    def capabilities(self):
        return self.data["capabilities"]

    def operation(self, operation_id):
        try:
            raw = self.data["operations"][operation_id]
        except KeyError as exc:
            raise DefinitionError(
                f"Unknown integration operation: {operation_id}"
            ) from exc
        retry = raw.get("retry", {})
        return OperationDefinition(
            operation_id,
            raw["method"],
            raw["path"],
            tuple(raw["success_codes"]),
            tuple(retry.get("retry_on", [])),
            bool(retry.get("safe", False)),
            bool(retry.get("network_errors", False)),
            int(retry.get("max_attempts", 1)),
            float(retry.get("backoff_seconds", 0)),
            raw,
        )


def write_connector(data, path=None):
    """Validate then atomically persist the complete contract with owner-only permissions."""
    target = Path(path or CONNECTOR_FILE)
    encoded = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    write_private(
        target,
        encoded,
        validator=IntegrationDefinition,
    )
