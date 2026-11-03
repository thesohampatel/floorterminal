"""Literal, non-executable field paths for connector payloads and responses."""

from .definition import DefinitionError


def read_field(value, path, default=None):
    # Compact directory snapshots retain only the explicitly mapped leaves.
    if isinstance(value, dict) and path in value:
        return value[path]
    for name in path.split("."):
        if not isinstance(value, dict) or name not in value:
            return default
        value = value[name]
    return value


def expand_fields(value):
    """Expand dotted request keys, including assignee objects, without code eval."""
    if isinstance(value, list):
        return [expand_fields(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for path, item in value.items():
        parts = path.split(".")
        if any(not part for part in parts):
            raise DefinitionError("Request field paths cannot have empty segments")
        target = result
        for name in parts[:-1]:
            target = target.setdefault(name, {})
            if not isinstance(target, dict):
                raise DefinitionError("Request field paths overlap")
        if parts[-1] in target:
            raise DefinitionError("Request field paths overlap")
        target[parts[-1]] = expand_fields(item)
    return result
