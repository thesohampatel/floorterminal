"""Secure catalog-driven request preparation, transport, and error handling."""

from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .definition import DefinitionError, IntegrationDefinition


class IntegrationError(RuntimeError):
    def __init__(self, message, code="UNKNOWN", status=None, retry_after=None):
        super().__init__(message)
        self.code, self.status, self.retry_after = code, status, retry_after


@dataclass(frozen=True)
class PreparedRequest:
    operation_id: str
    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None
    success_codes: tuple[int, ...]
    retry_codes: tuple[int, ...]
    retry_safe: bool
    retry_network_errors: bool
    retry_max_attempts: int
    retry_backoff_seconds: float
    response_body_path: str


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: object
    body: bytes


class TransportHTTPError(Exception):
    def __init__(self, status, headers, body):
        super().__init__(status)
        self.status, self.headers, self.body = status, headers, body


class UrllibTransport:
    """The only production network boundary; tests inject a non-network transport."""

    MAX_RESPONSE_BYTES = 4 * 1024 * 1024

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    @classmethod
    def _read_response(cls, response):
        try:
            declared = int(response.headers.get("Content-Length", 0))
        except (TypeError, ValueError, AttributeError):
            declared = 0
        if declared > cls.MAX_RESPONSE_BYTES:
            raise IntegrationError(
                "Integration response exceeds the 4 MiB safety limit",
                "RESPONSE_TOO_LARGE",
            )
        body = response.read(cls.MAX_RESPONSE_BYTES + 1)
        if len(body) > cls.MAX_RESPONSE_BYTES:
            raise IntegrationError(
                "Integration response exceeds the 4 MiB safety limit",
                "RESPONSE_TOO_LARGE",
            )
        return body

    def send(self, prepared: PreparedRequest, timeout: float) -> TransportResponse:
        if os.environ.get("FLOORTERMINAL_DISABLE_NETWORK") == "1":
            raise IntegrationError(
                "Network disabled by the process environment", "UNAVAILABLE"
            )
        request = Request(
            prepared.url,
            data=prepared.body,
            headers=prepared.headers,
            method=prepared.method,
        )
        try:
            with build_opener(self.NoRedirect()).open(
                request, timeout=timeout
            ) as response:
                return TransportResponse(
                    response.status, response.headers, self._read_response(response)
                )
        except HTTPError as exc:
            raise TransportHTTPError(
                exc.code, exc.headers, self._read_response(exc)
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise IntegrationError(
                f"Network unavailable: {reason}", "UNAVAILABLE"
            ) from exc


class IntegrationClient:
    """Execute named operations from the single external integration contract."""

    PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
    PATH_VALUE = re.compile(r"\{([A-Za-z0-9_]+)\}")

    @staticmethod
    def _safe_remote_detail(value, limit=500, sensitive_values=()):
        """Bound untrusted remote error text and remove terminal control bytes."""
        if isinstance(value, (dict, list)):
            value = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        text = str(value)
        # Some remote errors echo authentication data, including derived Basic
        # credentials. Redact before truncation and before retaining diagnostics.
        secrets = {str(item) for item in sensitive_values if item}
        secrets.update(
            json.dumps(item, ensure_ascii=False)[1:-1] for item in tuple(secrets)
        )
        for secret in sorted(secrets, key=len, reverse=True):
            text = text.replace(secret, "[REDACTED]")
        text = " ".join(text.splitlines())
        text = "".join(
            character
            for character in text
            if 32 <= ord(character) < 127 or ord(character) >= 160
        )
        return text[:limit] + ("…" if len(text) > limit else "")

    def __init__(self, definition=None, config=None, logger=None, transport=None):
        self.definition = (
            definition
            if isinstance(definition, IntegrationDefinition)
            else IntegrationDefinition(definition)
        )
        self.credentials = self.definition.credentials
        self.authentication_values = self._authentication_values()
        self.config, self.logger = config or {}, logger
        self.transport = transport or UrllibTransport()
        self.local_request_times, self.lock = deque(), threading.Lock()
        self.limit = self.remaining = self.reset = self.window_resets_at = None
        self.session_used = 0

    def reconfigure(self, definition, config, logger=None):
        self.definition = (
            definition
            if isinstance(definition, IntegrationDefinition)
            else IntegrationDefinition(definition)
        )
        self.credentials = self.definition.credentials
        self.authentication_values = self._authentication_values()
        self.config, self.logger = config, logger

    def _substitute(self, template, values, credential=False):
        pattern = self.PLACEHOLDER if credential else self.PATH_VALUE

        def replace(match):
            name = match.group(1)
            value = str(values.get(name, "")).strip()
            if not value:
                raise DefinitionError(f"Missing required integration value: {name}")
            if credential and ("\r" in value or "\n" in value):
                raise DefinitionError(
                    f"Credential {name} contains prohibited line breaks"
                )
            return value if credential else quote(value, safe="")

        result = pattern.sub(replace, str(template))
        if "${" in result or (not credential and self.PATH_VALUE.search(result)):
            raise DefinitionError("Unresolved integration placeholder")
        return result

    def _authentication_values(self):
        values = dict(self.credentials)
        derived = self.definition.data.get("authentication", {}).get(
            "derived_credentials", {}
        )
        for name, definition in derived.items():
            sources = self.PLACEHOLDER.findall(definition.get("template", ""))
            if any(not str(values.get(source, "")).strip() for source in sources):
                values[name] = ""
                continue
            value = self._substitute(definition.get("template", ""), values, True)
            transform = definition.get("transform", "none")
            if transform == "base64":
                value = base64.b64encode(value.encode("utf-8")).decode("ascii")
            elif transform == "urlencode":
                value = quote(value, safe="")
            values[name] = value
        return values

    @staticmethod
    def _merge_path(target, dotted_path, value):
        if not dotted_path:
            if not isinstance(value, dict):
                raise DefinitionError("Root request merge requires an object")
            target.update(value)
            return
        cursor = target
        parts = dotted_path.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
            if not isinstance(cursor, dict):
                raise DefinitionError(
                    f"Request envelope path is not an object: {dotted_path}"
                )
        cursor[parts[-1]] = value

    def _request_body(self, operation, body):
        definition = operation.raw.get("body", {})
        encoding = definition.get("encoding", "json")
        if encoding == "none" or body is None and not definition.get("static"):
            return None, None
        result = json.loads(json.dumps(definition.get("static", {})))
        if body is not None:
            self._merge_path(result, definition.get("payload_path", ""), body)
        for name, template in (
            self.definition.data.get("authentication", {}).get("body", {}).items()
        ):
            self._merge_path(
                result,
                name,
                self._substitute(template, self.authentication_values, True),
            )
        if encoding == "form":
            return urlencode(result, doseq=True).encode(
                "utf-8"
            ), "application/x-www-form-urlencoded"
        return json.dumps(result, separators=(",", ":")).encode(
            "utf-8"
        ), "application/json"

    @staticmethod
    def _extract_path(value, path):
        for key in filter(None, str(path).split(".")):
            value = value.get(key) if isinstance(value, dict) else None
        if value is None:
            raise IntegrationError(
                "Integration response is missing its configured response path",
                "INVALID_RESPONSE",
            )
        return value

    def _validate_value(self, value, schema, field="request body"):
        if not schema:
            return
        expected = schema.get("type")
        types = {
            "object": dict,
            "array": list,
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
        }
        if expected in types and (
            not isinstance(value, types[expected])
            or expected in {"integer", "number"}
            and isinstance(value, bool)
        ):
            raise DefinitionError(f"{field} must be {expected}")
        if "enum" in schema and value not in schema["enum"]:
            raise DefinitionError(f"{field} has an unsupported value")
        if isinstance(value, str) and len(value) < schema.get("minLength", 0):
            raise DefinitionError(f"{field} is too short")
        if isinstance(value, (int, float)) and value < schema.get("minimum", value):
            raise DefinitionError(f"{field} is below its minimum")
        if isinstance(value, dict):
            missing = [name for name in schema.get("required", []) if name not in value]
            if missing:
                raise DefinitionError(f"{field} is missing: {', '.join(missing)}")
            properties = schema.get("properties", {})
            if schema.get("additionalProperties") is False:
                unknown = set(value) - set(properties)
                if unknown:
                    raise DefinitionError(
                        f"{field} has unsupported fields: {', '.join(sorted(unknown))}"
                    )
            for name, item in value.items():
                if name in properties:
                    self._validate_value(item, properties[name], f"{field}.{name}")
        if isinstance(value, list) and schema.get("items"):
            for index, item in enumerate(value):
                self._validate_value(item, schema["items"], f"{field}[{index}]")

    @staticmethod
    def _idempotency_key(value):
        value = str(value or "").strip()
        if not value or len(value) > 128 or "\r" in value or "\n" in value:
            raise DefinitionError(
                "A valid idempotency key is required for this operation"
            )
        return value

    def prepare(
        self, operation_id, path=None, query=None, body=None, idempotency_key=None
    ):
        if not self.definition.enabled:
            raise IntegrationError("External integration is disabled", "NOT_CONFIGURED")
        operation = self.definition.operation(operation_id)
        request_definition = operation.raw
        idempotency = request_definition.get("idempotency")
        if idempotency:
            key = self._idempotency_key(idempotency_key)
            location, name = idempotency["location"], idempotency["name"]
            if location == "query":
                query = dict(query or {})
                query[name] = key
            elif location == "body":
                body = json.loads(json.dumps(body or {}))
                self._merge_path(body, name, key)
        static_query = dict(request_definition.get("static_query", {}))
        authentication_query = self.definition.data.get("authentication", {}).get(
            "query", {}
        )
        for name, template in authentication_query.items():
            static_query[name] = self._substitute(
                template, self.authentication_values, True
            )
        query_aliases = request_definition.get("query_aliases", {})
        resolved_query = static_query | {
            query_aliases.get(key, key): value for key, value in (query or {}).items()
        }
        allowed_query = set(request_definition.get("query_parameters", []))
        unknown_query = set(resolved_query) - allowed_query
        if unknown_query:
            raise DefinitionError(
                f"Unsupported query parameters for {operation_id}: {', '.join(sorted(unknown_query))}"
            )
        self._validate_value(body, request_definition.get("body_schema"))
        connection = self.definition.data["connection"]
        base_url = self._substitute(
            connection["base_url"], self.authentication_values, True
        ).rstrip("/")
        operation_path = self._substitute(operation.path, path or {}, False)
        url = base_url + operation_path
        if resolved_query:
            clean = {
                key: value
                for key, value in resolved_query.items()
                if value is not None and value != ""
            }
            if clean:
                url += "?" + urlencode(clean, doseq=True)
        allowed_host = urlparse(base_url).hostname
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != allowed_host
            or parsed.username
        ):
            raise DefinitionError(
                "Resolved integration URL violates TLS or host policy"
            )
        headers = {"Content-Type": "application/json"}
        auth = self.definition.data.get("authentication", {})
        for name, template in auth.get("headers", {}).items():
            required_names = self.PLACEHOLDER.findall(str(template))
            if any(
                not self.authentication_values.get(item, "").strip()
                for item in required_names
            ):
                required = set(auth.get("required_credentials", []))
                if any(item in required for item in required_names):
                    raise DefinitionError(
                        f"Missing required credential for header {name}"
                    )
                continue
            headers[name] = self._substitute(template, self.authentication_values, True)
        for name, template in request_definition.get("headers", {}).items():
            headers[name] = self._substitute(template, self.authentication_values, True)
        if idempotency and idempotency["location"] == "header":
            headers[idempotency["name"]] = key
        encoded, content_type = self._request_body(operation, body)
        if content_type:
            headers["Content-Type"] = content_type
        return PreparedRequest(
            operation_id,
            operation.method,
            url,
            headers,
            encoded,
            operation.success_codes,
            operation.retry_codes,
            operation.retry_safe,
            operation.retry_network_errors,
            operation.retry_max_attempts,
            operation.retry_backoff_seconds,
            str(operation.raw.get("response_body_path", "")),
        )

    def _budget(self):
        now = time.monotonic()
        budget = min(
            10,
            max(
                1,
                int(self.definition.data["connection"].get("requests_per_minute", 10)),
            ),
        )
        with self.lock:
            while self.local_request_times and now - self.local_request_times[0] >= 60:
                self.local_request_times.popleft()
            if len(self.local_request_times) >= budget:
                retry = max(1, int(61 - (now - self.local_request_times[0])))
                raise IntegrationError(
                    f"Application API limit reached ({len(self.local_request_times)}/{budget}); retry in {retry} seconds",
                    "RATE_LIMITED",
                    429,
                    retry,
                )
            self.local_request_times.append(now)
        return budget

    @property
    def app_window_used(self):
        now = time.monotonic()
        with self.lock:
            while self.local_request_times and now - self.local_request_times[0] >= 60:
                self.local_request_times.popleft()
            return len(self.local_request_times)

    def _rates(self, headers):
        def number(name):
            try:
                return int(headers.get(name))
            except (TypeError, ValueError, AttributeError):
                return None

        names = self.definition.data.get("response", {}).get("rate_limit_headers", {})
        self.limit = number(names.get("limit", "X-Rate-Limit-Limit")) or self.limit
        self.remaining = number(names.get("remaining", "X-Rate-Limit-Remaining"))
        self.reset = number(names.get("reset_seconds", "X-Rate-Limit-Reset"))
        if self.reset is not None:
            self.window_resets_at = time.monotonic() + self.reset

    def _log(self, event, level="INFO", **details):
        if self.logger:
            self.logger.log(
                event, level, integration=self.definition.display_name, **details
            )

    def execute(
        self, operation_id, path=None, query=None, body=None, idempotency_key=None
    ):
        prepared = self.prepare(
            operation_id, path, query, body, idempotency_key=idempotency_key
        )
        started = time.monotonic()
        self._log(
            "integration_request_started",
            operation=operation_id,
            method=prepared.method,
        )
        response = None
        budget = 0
        attempt = 0
        while attempt < prepared.retry_max_attempts:
            attempt += 1
            budget = self._budget()
            try:
                response = self.transport.send(
                    prepared,
                    float(
                        self.definition.data["connection"].get("timeout_seconds", 15)
                    ),
                )
                if response.status not in prepared.success_codes:
                    raise TransportHTTPError(
                        response.status, response.headers, response.body
                    )
                break
            except TransportHTTPError as exc:
                should_retry = (
                    prepared.retry_safe
                    and exc.status in prepared.retry_codes
                    and attempt < prepared.retry_max_attempts
                )
                if not should_retry:
                    return self._raise_http_error(
                        prepared, operation_id, exc, started, attempt
                    )
                self._log(
                    "integration_request_retrying",
                    "WARNING",
                    operation=operation_id,
                    method=prepared.method,
                    status=exc.status,
                    attempt=attempt,
                )
            except IntegrationError as exc:
                should_retry = (
                    prepared.retry_safe
                    and prepared.retry_network_errors
                    and exc.code == "UNAVAILABLE"
                    and attempt < prepared.retry_max_attempts
                )
                if not should_retry:
                    self._log(
                        "integration_request_failed",
                        "ERROR",
                        operation=operation_id,
                        method=prepared.method,
                        error_code=exc.code,
                        attempt=attempt,
                    )
                    raise
                self._log(
                    "integration_request_retrying",
                    "WARNING",
                    operation=operation_id,
                    method=prepared.method,
                    error_code=exc.code,
                    attempt=attempt,
                )
            if prepared.retry_backoff_seconds:
                time.sleep(prepared.retry_backoff_seconds)
        if response is None:
            raise IntegrationError(
                "Integration request did not complete", "UNAVAILABLE"
            )
        self._rates(response.headers)
        self.session_used += 1
        self._log(
            "integration_request_completed",
            operation=operation_id,
            method=prepared.method,
            status=response.status,
            duration_ms=round((time.monotonic() - started) * 1000),
            remaining=self.remaining,
            limit=self.limit,
            app_window_used=self.app_window_used,
            app_window_limit=budget,
            attempts=attempt,
        )
        if not response.body:
            return {}
        try:
            parsed = json.loads(response.body)
            return self._extract_path(parsed, prepared.response_body_path)
        except (ValueError, UnicodeDecodeError) as exc:
            raise IntegrationError(
                "Integration returned invalid JSON",
                "INVALID_RESPONSE",
                response.status,
            ) from exc

    def _raise_http_error(self, prepared, operation_id, exc, started, attempt):
        """Normalize one final HTTP failure without exposing request data."""
        self._rates(exc.headers)
        error_map = self.definition.data.get("response", {}).get("error_status_map", {})
        code = error_map.get(str(exc.status), "UNKNOWN")
        text = exc.body.decode("utf-8", "replace")
        try:
            parsed = json.loads(text)
            value = parsed
            if isinstance(parsed, dict):
                value = (
                    parsed.get("error")
                    or parsed.get("message")
                    or parsed.get("errors")
                    or parsed
                )
            detail = self._safe_remote_detail(
                value, sensitive_values=self.authentication_values.values()
            )
        except ValueError:
            detail = self._safe_remote_detail(
                text, sensitive_values=self.authentication_values.values()
            )
        self._log(
            "integration_request_failed",
            "ERROR",
            operation=operation_id,
            method=prepared.method,
            status=exc.status,
            error_code=code,
            attempt=attempt,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        raise IntegrationError(
            f"Integration request failed ({exc.status}): {detail}", code, exc.status
        ) from exc
