"""Optional, strictly bounded availability check against the hardcoded channel.

This check only ever answers one question: has the maintainer published a newer
version? It never downloads software, never authenticates, sends no deployment
data, and cannot influence what the terminal installs — installation is exclusively
an offline, operator-authorized action from verified removable media.

The endpoint, the host, and the accepted signing keys are compiled into the build,
so a deployment cannot be pointed at another server by configuration, environment,
DNS-supplied metadata, or a redirect. Every failure is a reportable status, never
an exception that reaches the workflow.
"""

from __future__ import annotations

import base64
import json
import math
import os
import ssl
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from ..core.config import write_json
from . import manifest, trust, version

SIGNATURE_URL = f"{trust.UPDATE_CHANNEL_URL}.sig"

OUTCOME_OK = "ok"
OUTCOME_UNAVAILABLE = "unavailable"
OUTCOME_UNTRUSTED = "untrusted"
OUTCOME_DISABLED = "disabled"


class ChannelError(RuntimeError):
    """Raised when the update channel cannot be reached or cannot be trusted."""

    def __init__(self, message, outcome=OUTCOME_UNAVAILABLE):
        super().__init__(message)
        self.outcome = outcome


def _http_detail(status):
    """Explain a channel response in terms an operator can act on."""
    if status == 404:
        return (
            "The published release channel could not be read (HTTP 404). It may not "
            "be published yet, or this terminal has no route to it. Check the "
            "project releases page from another computer."
        )
    if status in {401, 403}:
        return (
            f"The release channel refused this request (HTTP {status}). A network "
            "filter or proxy is most likely intercepting it."
        )
    return f"The release channel returned HTTP {status}."


class _NoRedirect(HTTPRedirectHandler):
    """Refuse every redirect; the update channel location is not negotiable."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _context():
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _fetch(url, maximum, timeout=None):
    if any(
        os.environ.get(name) == "1"
        for name in (
            "FLOORTERMINAL_DISABLE_NETWORK",
            "FLOORTERMINAL_DISABLE_UPDATE_NETWORK",
        )
    ):
        raise ChannelError(
            "Network disabled by the process environment", OUTCOME_DISABLED
        )
    parsed = urlparse(url)
    if (
        url not in {trust.UPDATE_CHANNEL_URL, SIGNATURE_URL}
        or parsed.scheme != "https"
        or parsed.hostname != trust.UPDATE_CHANNEL_HOST
    ):
        raise ChannelError(
            f"Refusing a non-HTTPS or off-channel update URL: {url}", OUTCOME_UNTRUSTED
        )
    request = Request(
        url,
        method="GET",
        headers={
            "User-Agent": trust.USER_AGENT,
            "Accept": "application/json",
            "Cache-Control": "no-cache",
        },
    )
    opener = build_opener(_NoRedirect(), HTTPSHandler(context=_context()))
    try:
        with opener.open(
            request, timeout=timeout or trust.NETWORK_TIMEOUT_SECONDS
        ) as response:
            if response.status != 200:
                raise ChannelError(_http_detail(response.status))
            try:
                declared = int(response.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                declared = 0
            if declared > maximum:
                raise ChannelError("Update channel response exceeds the safety limit")
            body = response.read(maximum + 1)
    except HTTPError as exc:
        raise ChannelError(_http_detail(exc.code)) from exc
    except URLError as exc:
        raise ChannelError(f"Update channel is unreachable: {exc.reason}") from exc
    except (TimeoutError, OSError, ValueError) as exc:
        raise ChannelError(f"Update channel request failed: {exc}") from exc
    if len(body) > maximum:
        raise ChannelError("Update channel response exceeds the safety limit")
    return body


def fetch_channel(fetcher=None) -> manifest.ChannelDocument:
    """Retrieve and verify the published availability announcement."""
    fetcher = fetcher or _fetch
    document = fetcher(trust.UPDATE_CHANNEL_URL, trust.MAX_CHANNEL_RESPONSE_BYTES)
    signature = fetcher(SIGNATURE_URL, trust.MAX_SIGNATURE_BYTES)
    try:
        return manifest.load_verified_channel(document, signature)
    except manifest.ManifestError as exc:
        raise ChannelError(str(exc), OUTCOME_UNTRUSTED) from exc


@dataclass(frozen=True)
class ChannelResult:
    """Cached outcome of the most recent availability check."""

    outcome: str
    checked_at_epoch: float = 0.0
    checked_at_utc: str = ""
    detail: str = ""
    version: str = ""
    released_utc: str = ""
    release_title: str = ""
    release_summary: str = ""
    minimum_upgradable_version: str = ""
    archive_name: str = ""
    archive_sha256: str = ""
    artifact_sha256: str = ""
    artifact_size_bytes: int = 0
    notes_url: str = ""
    signing_key_id: str = ""
    features: tuple = ()
    fixes: tuple = ()
    security: tuple = ()
    published_utc: str = ""
    targets: tuple = ()
    document_base64: str = ""
    signature_base64: str = ""

    @property
    def successful(self):
        return self.outcome == OUTCOME_OK and bool(self.version)

    def age_seconds(self, now):
        return max(0.0, float(now) - self.checked_at_epoch)

    def is_stale(self, now):
        return (
            self.checked_at_epoch > float(now) + 300
            or self.age_seconds(now) > trust.CHECK_FRESHNESS_SECONDS
        )

    def highlights(self):
        return (
            *(("NEW", item) for item in self.features),
            *(("FIX", item) for item in self.fixes),
            *(("SECURITY", item) for item in self.security),
        )


def result_from_channel(channel: manifest.ChannelDocument, now) -> ChannelResult:
    """Convert a verified channel document into a cacheable result."""
    release = channel.release
    return ChannelResult(
        outcome=OUTCOME_OK,
        checked_at_epoch=float(now),
        checked_at_utc=datetime.fromtimestamp(float(now), UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        version=release.version,
        released_utc=release.released_utc,
        release_title=release.release_title,
        release_summary=release.release_summary,
        minimum_upgradable_version=release.minimum_upgradable_version,
        archive_name=channel.archive_name,
        archive_sha256=channel.archive_sha256,
        artifact_sha256=release.artifact_sha256,
        artifact_size_bytes=release.artifact_size_bytes,
        notes_url=release.notes_url,
        signing_key_id=channel.signing_key_id,
        features=release.features,
        fixes=release.fixes,
        security=release.security,
        published_utc=channel.published_utc,
        targets=channel.targets,
        document_base64=base64.b64encode(channel.document_bytes).decode("ascii"),
        signature_base64=base64.b64encode(channel.signature_bytes).decode("ascii"),
    )


def failure_result(outcome, detail, now) -> ChannelResult:
    return ChannelResult(
        outcome=outcome,
        checked_at_epoch=float(now),
        checked_at_utc=datetime.fromtimestamp(float(now), UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        detail=str(detail)[:300],
    )


def save_cache(path, result: ChannelResult):
    """Persist the last check so the panel stays informative without a network."""
    payload = {"schema_version": manifest.SCHEMA_VERSION, **asdict(result)}
    payload["features"] = list(result.features)
    payload["fixes"] = list(result.fixes)
    payload["security"] = list(result.security)
    try:
        # Also covers an unmanaged installation, where nothing else has created
        # the update directory yet. Caching keeps the panel useful offline.
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_json(path, payload)
    except OSError:
        return False
    return True


def load_cache(path) -> ChannelResult | None:
    """Reauthenticate cached metadata; unsigned legacy summaries are not evidence."""
    try:
        if path.is_symlink():
            return None
        with path.open("rb") as stream:
            raw = stream.read(trust.MAX_CHANNEL_RESPONSE_BYTES * 2 + 1)
        if len(raw) > trust.MAX_CHANNEL_RESPONSE_BYTES * 2:
            return None
        data = json.loads(raw)
        if (
            not isinstance(data, dict)
            or data.get("schema_version") != manifest.SCHEMA_VERSION
        ):
            return None
        checked = data.get("checked_at_epoch")
        if isinstance(checked, bool) or not isinstance(checked, (int, float)):
            return None
        if not math.isfinite(checked) or checked < 0:
            return None
        if data.get("outcome") != OUTCOME_OK:
            outcome = data.get("outcome")
            if outcome not in {
                OUTCOME_UNAVAILABLE,
                OUTCOME_DISABLED,
                OUTCOME_UNTRUSTED,
            }:
                return None
            return failure_result(outcome, str(data.get("detail", "")), checked)
        document = base64.b64decode(data["document_base64"], validate=True)
        signature = base64.b64decode(data["signature_base64"], validate=True)
        channel = manifest.load_verified_channel(document, signature)
        return result_from_channel(channel, checked)
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        manifest.ManifestError,
    ):
        return None


def validate_progression(candidate: ChannelResult, previous: ChannelResult | None):
    """An older or same-version substituted announcement cannot erase known truth."""
    if version.parse(candidate.version).release_rank == 0:
        raise ChannelError(
            "The stable channel announced a release candidate", OUTCOME_UNTRUSTED
        )
    if not previous or not previous.successful:
        return
    if version.compare(candidate.version, previous.version) < 0 or (
        candidate.published_utc
        and previous.published_utc
        and candidate.published_utc < previous.published_utc
    ):
        raise ChannelError(
            "The channel returned older metadata; the last verified release is retained",
            OUTCOME_UNTRUSTED,
        )
    if candidate.version == previous.version and (
        candidate.artifact_sha256,
        candidate.artifact_size_bytes,
        candidate.archive_name,
        candidate.archive_sha256,
    ) != (
        previous.artifact_sha256,
        previous.artifact_size_bytes,
        previous.archive_name,
        previous.archive_sha256,
    ):
        raise ChannelError(
            "Different executable contents claim the same release version",
            OUTCOME_UNTRUSTED,
        )
