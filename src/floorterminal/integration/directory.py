"""Bounded, resumable read-only directories; never a cache for external writes."""

import json
import time
from copy import deepcopy

from .mapping import read_field
from .runtime import IntegrationError

MAX_STREAMS = 16
MAX_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 10000
COMPLETE_TTL = 300
PARTIAL_TTL = 1800


def read_directory(owner, collection, operation, path=None, query=None):
    now = time.monotonic()
    cache = owner.directory_progress
    for key, value in list(cache.items()):
        if value["expires"] <= now:
            del cache[key]
    pages = max(1, min(20, int(owner.config.get("directory_max_pages", 3))))
    key = json.dumps([collection, operation, path, query, pages], sort_keys=True)
    if key not in cache:
        while len(cache) >= MAX_STREAMS:
            del cache[next(iter(cache))]
        cache[key] = {
            "expires": now + PARTIAL_TTL,
            "items": [],
            "cursor": None,
            "seen": [],
            "pages": 0,
            "complete": False,
        }
    progress = cache[key]
    definition = owner.definition.operation(owner._operation(operation)).raw
    aliases = definition.get("query_aliases", {})
    allowed = definition["query_parameters"]
    # Keep only the directory fields used by the application, not arbitrary
    # provider payloads, personal details or response metadata.
    fields = {
        owner._field(k, v)
        for k, v in (
            ("id", "id"),
            ("name", "name"),
            ("first_name", "firstName"),
            ("last_name", "lastName"),
        )
    }
    while not progress["complete"]:
        if progress["pages"] >= pages:
            raise IntegrationError(
                "Directory is incomplete at the configured page limit; increase directory_max_pages or narrow its server-side scope",
                "INVALID_RESPONSE",
            )
        page_query = dict(query or {})
        if aliases.get("limit", "limit") in allowed:
            page_query.setdefault(
                "limit", definition.get("directory", {}).get("page_size", 200)
            )
        if progress["cursor"] is not None:
            if aliases.get("cursor", "cursor") not in allowed:
                raise IntegrationError(
                    "Directory requires a configured cursor query parameter",
                    "INVALID_RESPONSE",
                )
            page_query["cursor"] = progress["cursor"]
        # Failure leaves the last successful cursor intact. The next scheduled
        # attempt resumes here, rather than spending its quota on page one again.
        data = owner._execute(operation, path=path, query=page_query)
        if not isinstance(data, (dict, list)):
            raise IntegrationError(
                "Directory response must be an object or array", "INVALID_RESPONSE"
            )
        records = [
            {
                key: read_field(item, key)
                for key in fields
                if read_field(item, key) is not None
            }
            for item in owner._collection(collection, data)
            if isinstance(item, dict)
        ]
        for record in records:
            identifier = record.get(owner._field("id", "id"))
            if (
                isinstance(identifier, bool)
                or not isinstance(identifier, (int, str))
                or not str(identifier).strip()
            ):
                raise IntegrationError(
                    "Directory entry has no usable identifier", "INVALID_RESPONSE"
                )
        cursor = read_field(data, owner._field("next_cursor", "nextCursor"))
        if cursor is not None and (
            isinstance(cursor, bool)
            or not isinstance(cursor, (str, int))
            or len(str(cursor)) > 4096
        ):
            raise IntegrationError("Directory cursor is invalid", "INVALID_RESPONSE")
        candidate = deepcopy(progress)
        candidate["items"].extend(records)
        candidate["pages"] += 1
        marker = str(cursor) if cursor is not None else ""
        if marker and marker in candidate["seen"]:
            raise IntegrationError(
                "Directory repeated a pagination cursor; lookup is incomplete",
                "INVALID_RESPONSE",
            )
        candidate["complete"] = not marker
        candidate["cursor"] = cursor
        candidate["seen"].append(marker)
        candidate["expires"] = time.monotonic() + (
            COMPLETE_TTL if candidate["complete"] else PARTIAL_TTL
        )
        if (
            len(candidate["items"]) > MAX_RECORDS
            or len(json.dumps({**cache, key: candidate}, allow_nan=False).encode())
            > MAX_BYTES
        ):
            cache.pop(key, None)
            raise IntegrationError(
                "Directory exceeds safe lookup capacity; narrow its server-side scope",
                "INVALID_RESPONSE",
            )
        cache[key] = progress = candidate
    return deepcopy(progress["items"])


def refresh_completed(owner, collections=None):
    """Explicit refresh discards complete snapshots, not unfinished pagination."""
    owner.directory_progress = {
        key: value
        for key, value in owner.directory_progress.items()
        if not value["complete"]
        or collections is not None
        and json.loads(key)[0] not in collections
    }
