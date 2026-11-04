"""Three configurable message-only shortcuts, independent of incident routing."""

SLOTS = ("engineering", "quality", "production")


def support_buttons(config):
    """Resolve legacy destinations without rewriting deployment configuration."""
    configured = config.get("support_buttons")
    if configured is None:
        configured = [
            {
                "label": key.title(),
                "destination": str(config.get(key + "_chat_name", "") or ""),
                "enabled": True,
            }
            for key in SLOTS
        ]
    return [dict(button, key=key) for key, button in zip(SLOTS, configured)]


def validate_support_buttons(value):
    if value is None:
        return
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("support_buttons must contain exactly three shortcut slots")
    for index, button in enumerate(value, 1):
        if not isinstance(button, dict) or set(button) != {
            "label",
            "destination",
            "enabled",
        }:
            raise ValueError(
                f"Support button {index}: use label, destination and enabled"
            )
        if type(button["enabled"]) is not bool:
            raise ValueError(f"Support button {index}: enabled must be true or false")
        for key, limit in (("label", 48), ("destination", 120)):
            text = button[key]
            if (
                not isinstance(text, str)
                or len(text) > limit
                or any(not char.isprintable() for char in text)
            ):
                raise ValueError(
                    f"Support button {index}: {key} must be one printable line, up to {limit} characters"
                )
        if not button["label"].strip():
            raise ValueError(f"Support button {index}: enter a label")
