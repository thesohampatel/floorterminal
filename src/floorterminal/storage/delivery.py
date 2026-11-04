"""Bounded, durable semantic delivery journal; never stores credentials or URLs."""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from copy import deepcopy

MAX_DELIVERIES = 512
MAX_JOURNAL_BYTES = 2 * 1024 * 1024
METHODS = {
    "create_response_record",
    "set_response_record_status",
    "assign_participants",
    "add_response_record_comment",
    "set_asset_status",
    "send_message",
}
PHASES = {"queued", "sending", "attention"}
LOCAL_PREFIX = "local:"
CONTEXT_FIELDS = {
    "asset_id",
    "location_id",
    "response_record_type",
    "directory_max_pages",
    "asset_ids",
    "location_ids",
    "group_ids",
    "group_names",
    "affected_stations",
    "reported_stations",
    "impact_scope",
    "incident_id",
    "failure_details",
}


def binding(provider):
    definition = getattr(provider, "definition", None)
    if definition is None:
        return ""
    data = definition.data
    # Hash routing identity, not credentials: key rotation must not strand work.
    identity = [data.get("connection", {}).get("base_url"), data.get("identity", {})]
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def validate_journal(entries):
    if not isinstance(entries, list) or len(entries) > MAX_DELIVERIES:
        raise ValueError("Delivery journal exceeds its 512-operation safety capacity")
    ids = set()
    for item in entries:
        if not isinstance(item, dict):
            raise TypeError("Invalid delivery entry")
        if set(item) != {
            "id",
            "method",
            "args",
            "kwargs",
            "binding",
            "context",
            "created_at",
            "attempts",
            "next_at",
            "phase",
            "error",
            "reference",
            "expires_at",
            "safe_retry",
        }:
            raise ValueError("Invalid delivery entry fields")
        try:
            uuid.UUID(item["id"])
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid delivery identifier") from exc
        if item["id"] in ids:
            raise ValueError("Duplicate delivery identifier")
        ids.add(item["id"])
        if item["method"] not in METHODS or item["phase"] not in PHASES:
            raise ValueError("Invalid delivery operation or phase")
        if not isinstance(item["args"], list) or not isinstance(item["kwargs"], dict):
            raise TypeError("Invalid delivery arguments")
        expected = {
            "create_response_record": 6,
            "set_response_record_status": 2,
            "assign_participants": 3,
            "add_response_record_comment": 2,
            "set_asset_status": 4,
            "send_message": 2,
        }
        if len(item["args"]) != expected[item["method"]]:
            raise ValueError("Invalid delivery argument count")
        if set(item["kwargs"]) - {"idempotency_key"}:
            raise ValueError("Invalid delivery keyword arguments")
        if (
            not isinstance(item["context"], dict)
            or set(item["context"]) - CONTEXT_FIELDS
        ):
            raise ValueError("Invalid delivery target context")
        if not isinstance(item["binding"], str) or (
            item["binding"]
            and (
                len(item["binding"]) != 64
                or any(c not in "0123456789abcdef" for c in item["binding"])
            )
        ):
            raise ValueError("Invalid delivery binding")
        expected_reference = (
            LOCAL_PREFIX + item["id"]
            if item["method"] == "create_response_record"
            else ""
        )
        if item["reference"] != expected_reference:
            raise ValueError("Invalid local record reference")
        if (
            not isinstance(item["safe_retry"], bool)
            or not isinstance(item["error"], str)
            or len(item["error"]) > 500
        ):
            raise ValueError("Invalid delivery retry metadata")
        if (
            isinstance(item["attempts"], bool)
            or not isinstance(item["attempts"], int)
            or item["attempts"] < 0
        ):
            raise ValueError("Invalid delivery attempt count")
        for name in ("created_at", "next_at", "expires_at"):
            value = item[name]
            if name == "expires_at" and value is None:
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError("Invalid delivery timestamp")
    if len(json.dumps(entries, allow_nan=False).encode()) > MAX_JOURNAL_BYTES:
        raise ValueError(
            "Delivery journal is full; restore synchronization before recording more external work"
        )


def enqueue(
    state,
    provider,
    method,
    args,
    kwargs,
    *,
    expires_at=None,
    context_override=None,
    binding_override=None,
):
    entries = state.setdefault("delivery_outbox", [])
    context = {
        key: provider.config[key]
        for key in (
            "asset_id",
            "location_id",
            "response_record_type",
            "directory_max_pages",
        )
        if key in provider.config
    }
    context.update(context_override or {})
    key = kwargs.get("idempotency_key") or str(uuid.uuid4())
    # Legacy queue conversion can be replayed after power loss before its removal.
    for existing in entries:
        if (
            existing["method"] == method
            and existing["args"] == list(args)
            and existing["kwargs"] == kwargs
            and existing["context"] == context
            and existing["binding"] == (binding_override or binding(provider))
        ):
            return existing
    item = {
        "id": str(key),
        "method": method,
        "args": deepcopy(list(args)),
        "kwargs": deepcopy(kwargs),
        "binding": binding_override or binding(provider),
        "context": context,
        "created_at": time.time(),
        "attempts": 0,
        "next_at": 0,
        "phase": "queued",
        "error": "",
        "reference": LOCAL_PREFIX + str(key)
        if method == "create_response_record"
        else "",
        "expires_at": expires_at,
        "safe_retry": False,
    }
    validate_journal([*entries, item])
    entries.append(item)
    return item


def replace_reference(value, old, new):
    """Resolve every pending dependency atomically with the creation acknowledgement."""
    if isinstance(value, str):
        return new if value == old else value.replace(old, str(new))
    if isinstance(value, list):
        return [replace_reference(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: replace_reference(item, old, new) for key, item in value.items()}
    return value
