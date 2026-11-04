"""Application-owned request budget, independent of the provider's shared quota."""

import threading
import time
from collections import deque


class RequestWindow:
    """Shared terminal ledger and live policy, including older in-flight clients."""

    def __init__(self):
        self.timestamps = deque()
        self.lock = threading.Lock()
        self.budget = None
        self.cooldown_until = 0.0

    def defer(self, seconds):
        with self.lock:
            self.cooldown_until = max(self.cooldown_until, time.monotonic() + seconds)

    def set_budget(self, value):
        value = positive_request_budget(value)
        with self.lock:
            self.budget = value


def positive_request_budget(value):
    """Accept a positive integer, never a bool, fraction, or unlimited sentinel."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("API requests per minute must be a positive whole number")
    return value


def request_budget(config, connection):
    """An explicit local setting overrides the connector's default budget."""
    value = config.get("api_requests_per_minute")
    if value is None:
        value = connection.get("requests_per_minute", 10)
    return positive_request_budget(value)
