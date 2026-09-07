"""Safe create-new-only connector templates for the guided Settings wizard."""

from __future__ import annotations

from urllib.parse import urlparse

from .definition import DefinitionError


def basic_diagnostic_connector(
    display_name, base_url, credential, diagnostic_path, auth_type
):
    name = " ".join(str(display_name).strip().split())
    base = str(base_url).strip().rstrip("/")
    path = "/" + str(diagnostic_path).strip().lstrip("/")
    parsed = urlparse(base)
    if not name:
        raise DefinitionError("Connector name is required")
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.query
        or parsed.fragment
    ):
        raise DefinitionError("Base URL must be a clean HTTPS URL")
    if not str(credential).strip():
        raise DefinitionError("Credential is required")
    if auth_type not in {"Bearer token", "X-API-Key"}:
        raise DefinitionError("Authentication type is unsupported")
    header = (
        {"Authorization": "Bearer ${access_token}"}
        if auth_type == "Bearer token"
        else {"X-API-Key": "${access_token}"}
    )
    return {
        "schema_version": 1,
        "contract": {
            "name": "FloorTerminal External Connector",
            "version": "1.0",
            "purpose": "User-managed external maintenance integration boundary",
        },
        "enabled": True,
        "identity": {
            "display_name": name,
            "description": "Guided diagnostic connector",
            "authenticated_subject_id": "",
        },
        "connection": {
            "protocol": "rest",
            "base_url": base,
            "timeout_seconds": 15,
            "requests_per_minute": 10,
            "allowed_hosts": [parsed.hostname],
        },
        "credentials": {"access_token": str(credential).strip()},
        "authentication": {
            "type": "bearer" if auth_type == "Bearer token" else "api_key",
            "required_credentials": ["access_token"],
            "optional_headers": [],
            "headers": header,
            "query": {},
            "body": {},
            "derived_credentials": {},
        },
        "capabilities": {
            "response_records": False,
            "response_record_status": False,
            "response_record_comments": False,
            "response_record_assignments": False,
            "asset_status": False,
            "messaging": False,
            "team_directory": False,
        },
        "diagnostics": {"test_operation": "diagnostic.get", "query": {}},
        "workflow": {
            "operations": {},
            "collections": {},
            "objects": {},
            "fields": {},
            "field_types": {},
            "values": {},
        },
        "operations": {
            "diagnostic.get": {
                "method": "GET",
                "path": path,
                "query_parameters": [],
                "success_codes": [200],
            }
        },
        "response": {
            "rate_limit_headers": {},
            "error_status_map": {
                "400": "INVALID_REQUEST",
                "401": "AUTHENTICATION",
                "403": "PERMISSION",
                "404": "NOT_FOUND",
                "429": "RATE_LIMITED",
                "500": "SERVER",
                "502": "UNAVAILABLE",
                "503": "UNAVAILABLE",
            },
        },
    }
