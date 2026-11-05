"""Secure catalog-driven request preparation, transport, and error handling."""

from __future__ import annotations

import base64
import json
import math
import os
import re
import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..core.json_file import decode_strict_json
from ..core.rate_policy import RequestWindow, request_budget
from .definition import DefinitionError, IntegrationDefinition


def retry_after_seconds(headers):
    """RFC 9110 Retry-After accepts delay-seconds or an HTTP date."""
    value = next(
        (
            str(value)
            for key, value in (headers or {}).items()
            if key.lower() == "retry-after"
        ),
        "",
    )
    try:
        if value.strip().isdigit():
            delay = int(value.strip())
        else:
            date = parsedate_to_datetime(value)
            delay = (date.astimezone(UTC) - datetime.now(UTC)).total_seconds()
        return max(0, math.ceil(delay)) if math.isfinite(delay) else None
    except (ValueError, TypeError, OverflowError):
        return None


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
            # HTTPError owns an open response too, including rejected/oversized
            # bodies. Do not leave sockets alive until exception GC during an
            # extended outage or a service repeatedly answering with 429/5xx.
            try:
                body = self._read_response(exc)
            finally:
                exc.close()
            raise TransportHTTPError(exc.code, exc.headers, body) from exc
        except (URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            error = IntegrationError(f"Network unavailable: {reason}", "UNAVAILABLE")
            error.no_request_sent = isinstance(
                reason, (socket.gaierror, ConnectionRefusedError)
            )
            raise error from exc


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
        secrets.update(quote(item, safe="") for item in tuple(secrets))
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
        self.bind_request_window(RequestWindow())
        self.limit = self.remaining = self.reset = self.window_resets_at = None
        self.session_used = 0

    def bind_request_window(self, window):
        self.request_window = window
        self.local_request_times, self.lock = window.timestamps, window.lock

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
            if not credential and (value in {".", ".."} or not value.isprintable()):
                raise DefinitionError(f"Invalid integration path value: {name}")
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
        return json.dumps(result, separators=(",", ":"), allow_nan=False).encode(
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
        if isinstance(value, str) and len(value) > schema.get("maxLength", len(value)):
            raise DefinitionError(f"{field} is too long")
        if isinstance(value, float) and not math.isfinite(value):
            raise DefinitionError(f"{field} must be finite")
        if isinstance(value, (int, float)) and value < schema.get("minimum", value):
            raise DefinitionError(f"{field} is below its minimum")
        if isinstance(value, (int, float)) and value > schema.get("maximum", value):
            raise DefinitionError(f"{field} is above its maximum")
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
        if not value or len(value) > 128 or not value.isprintable():
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
            elif location == "path":
                path = dict(path or {})
                if name in path and str(path[name]) != key:
                    raise DefinitionError(
                        "Idempotency path cannot replace a resource identifier"
                    )
                path[name] = key
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
        supplied_query = {
            query_aliases.get(key, key): value for key, value in (query or {}).items()
        }
        if set(supplied_query) & set(authentication_query):
            raise DefinitionError("Request query cannot override authentication fields")
        resolved_query = static_query | supplied_query
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
            or parsed.username is not None
            or parsed.fragment
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
        with self.lock:
            budget = self.request_window.budget
            if budget is None:
                budget = request_budget(self.config, self.definition.data["connection"])
            now = time.monotonic()
            if now < self.request_window.cooldown_until:
                retry = max(1, math.ceil(self.request_window.cooldown_until - now))
                raise IntegrationError(
                    "Connected service requested a pause; updates remain queued",
                    "RATE_LIMITED",
                    429,
                    retry,
                )
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
        headers = {str(k).casefold(): v for k, v in headers.items()}

        def number(name):
            try:
                value = int(headers.get(str(name).casefold()))
                return value if value >= 0 else None
            except (TypeError, ValueError, AttributeError):
                return None

        names = self.definition.data.get("response", {}).get("rate_limit_headers", {})
        self.limit = number(names.get("limit", "X-Rate-Limit-Limit")) or self.limit
        self.remaining = number(names.get("remaining", "X-Rate-Limit-Remaining"))
        self.reset = number(names.get("reset_seconds", "X-Rate-Limit-Reset"))
        if self.reset is not None:
            self.window_resets_at = time.monotonic() + self.reset
            if self.remaining == 0 and self.reset > 0:
                self.request_window.defer(self.reset)

    def _log(self, event, level="INFO", **details):
        if self.logger:
            self.logger.log(
                event, level, integration=self.definition.display_name, **details
            )

    def execute(
        self, operation_id, path=None, query=None, body=None, idempotency_key=None
    ):
        prepared = self.prepare(
            operation_id,
            path,
            query,
            body,
            idempotency_key=idempotency_key
            or getattr(self, "default_idempotency_key", None),
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
        max_attempts = getattr(
            self, "max_attempts_override", prepared.retry_max_attempts
        )
        while attempt < max_attempts:
            attempt += 1
            budget = self._budget()
            try:
                before_send = getattr(self, "before_send", None)
                if before_send:
                    before_send(prepared)
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
                    and exc.status != 429
                    and retry_after_seconds(exc.headers) is None
                    and exc.status in prepared.retry_codes
                    and attempt < max_attempts
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
                    and attempt < max_attempts
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
            parsed = decode_strict_json(response.body)
            return self._extract_path(parsed, prepared.response_body_path)
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            raise IntegrationError(
                "Integration returned invalid JSON",
                "INVALID_RESPONSE",
                response.status,
            ) from exc

    def _raise_http_error(self, prepared, operation_id, exc, started, attempt):
        """Normalize one final HTTP failure without exposing request data."""
        self._rates(exc.headers)
        if 200 <= exc.status < 300:
            # A write may already have succeeded. Never classify a connector's
            # incomplete success_codes mapping as a transient transport failure.
            # Do not echo a potentially sensitive successful response as an error.
            raise IntegrationError(
                f"Service returned HTTP {exc.status}, which is not in this operation's "
                "success_codes. Check remote delivery before correcting the connector or retrying.",
                "INVALID_RESPONSE",
                exc.status,
            ) from exc
        error_map = self.definition.data.get("response", {}).get("error_status_map", {})
        code = error_map.get(str(exc.status), "UNKNOWN")
        delay = retry_after_seconds(exc.headers)
        if exc.status == 429:
            code = "RATE_LIMITED"
            delay = delay if delay is not None else max(1, self.reset or 60)
        if delay is not None:
            self.request_window.defer(delay)
        sensitive = list(self.authentication_values.values())
        sensitive.extend(prepared.headers.values())
        for name, value in prepared.headers.items():
            if name.casefold() == "authorization":
                parts = value.split(None, 1)
                if len(parts) == 2:
                    sensitive.append(parts[1])
        # Literal authentication is supported too. Do not leak it when a remote
        # validation error echoes a header, query credential or body credential.
        auth = self.definition.data.get("authentication", {})
        for section in ("query", "body"):
            for template in auth.get(section, {}).values():
                try:
                    sensitive.append(
                        self._substitute(template, self.authentication_values, True)
                    )
                except DefinitionError:
                    # An unused optional credential was not present/sent.
                    continue
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
            detail = self._safe_remote_detail(value, sensitive_values=sensitive)
        except (ValueError, RecursionError):
            detail = self._safe_remote_detail(text, sensitive_values=sensitive)
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
            f"Integration request failed ({exc.status}): {detail}",
            code,
            exc.status,
            delay,
        ) from exc
