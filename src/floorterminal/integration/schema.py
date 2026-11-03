"""Small, explicit request-schema subset; unsupported rules never silently pass."""

import math


def validate_schema(schema, error, depth=0):
    if not isinstance(schema, dict) or depth > 24:
        raise error("Request schema must be a bounded object")
    allowed = {
        "type",
        "enum",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
    }
    if set(schema) - allowed:
        raise error("Request schema contains unsupported validation rules")
    if "type" in schema and schema["type"] not in (
        "object",
        "array",
        "string",
        "integer",
        "number",
        "boolean",
    ):
        raise error("Request schema type is unsupported")
    if "enum" in schema and (
        not isinstance(schema["enum"], list) or not schema["enum"]
    ):
        raise error("Request schema enum must be a nonempty array")
    required = schema.get("required", [])
    if not isinstance(required, list) or any(
        not isinstance(name, str) for name in required
    ):
        raise error("Request schema required must list field names")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise error("Request schema properties must be an object")
    for child in properties.values():
        validate_schema(child, error, depth + 1)
    if "additionalProperties" in schema and not isinstance(
        schema["additionalProperties"], bool
    ):
        raise error("Request schema additionalProperties must be boolean")
    if "items" in schema:
        validate_schema(schema["items"], error, depth + 1)
    for key in ("minimum", "maximum", "minLength", "maxLength"):
        if key not in schema:
            continue
        value = schema[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or isinstance(value, float)
            and not math.isfinite(value)
        ):
            raise error("Request schema bounds must be finite numbers")
        if key.endswith("Length") and (not isinstance(value, int) or value < 0):
            raise error("Request schema length bounds must be nonnegative integers")
    for lower, upper in (("minimum", "maximum"), ("minLength", "maxLength")):
        if lower in schema and upper in schema and schema[lower] > schema[upper]:
            raise error("Request schema minimum exceeds maximum")
