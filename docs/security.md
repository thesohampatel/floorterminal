# Security baseline

Operational audio accepts only fixed internal cue names, resolves assets within the
packaged directory, and invokes native players with argument arrays and no shell.
Audio failures are bounded, sanitized, and isolated from the reporting workflow.

This document records engineering alignment, not certification or a guarantee that
the software is vulnerability-free. Deployment owners must perform site-specific
risk assessment, acceptance testing, access control, patching, backups, network
segmentation, and incident response.

## Development baseline

The project uses [NIST SP 800-218 SSDF](https://csrc.nist.gov/pubs/sp/800/218/final)
as a secure-development vocabulary and
[CISA Secure by Design](https://www.cisa.gov/securebydesign) principles as design
guidance. Relevant controls include:

- reviewed changes, offline automated tests, static analysis, and build auditing;
- no tracked private credentials or production endpoints (the public initial
  Settings password is intentionally documented, not a production secret);
- minimal runtime dependencies and explicit build-tool versioning;
- private vulnerability reporting and documented supported versions;
- bounded input/response sizes, strict JSON validation, and fail-closed state load;
- HTTPS-only connectors, host allowlisting, no redirects, request throttling, and
  remotely enforced idempotency or explicit held-write recovery for non-repeatable operations;
- least-privilege file modes and a hardened Linux systemd sandbox;
- immutable build IDs, artifact hashes, release manifests, and retained notices;
- SPDX SBOM generation for the application artifact and build tool;
- signed offline software updates with build-time trust anchors, an immutable
  release endpoint, data-only removable media, atomic version activation,
  supervised automatic rollback, and attributed authorization.

[OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/)
is used only as a source of applicable verification ideas. This is a local
touchscreen application rather than a web application, so web-only controls are
not claimed.

## Integrity controls

- Authorized updates validate runtime data before switching and retain private,
  bounded checkpoints. These can contain connector credentials; they are not
  encrypted and must never be published or mirrored to USB. Future authenticated
  candidates check a detached copy through a bounded headless protocol with
  external connections disabled. This is not a sandbox against malicious signed
  code. Old operational queues and credentials are never automatically restored.
  See [update data safety](update-data-compatibility.md).

- Authentication throttle and Settings credential files are limited to 4 KiB
  through the same checked-descriptor JSON reader. Duplicate keys, non-finite
  numbers, invalid shapes, named pipes, hard links and final symlinks are rejected.
  Invalid throttle state starts a conservative 60-second delay without blocking
  operator startup or overwriting unsafe files. A failed durable throttle clear
  restores its in-memory protection; administrator access is not granted.
- Audit appends verify regular/single-link descriptors before writing or changing
  permissions, with nonblocking opens to avoid a named-pipe stall. Rotation
  validates its destinations first; maintenance skips hard-linked files.
  These are defense-in-depth checks, not protection against an administrator
  controlling the process or its parent directories.
- HTTP error objects own file-like responses too. Connector and update transports
  close those responses explicitly, even if body validation/read fails, so repeated
  outages do not rely on garbage collection to release sockets. See
  [Python HTTPError behavior](https://docs.python.org/3/library/urllib.error.html#urllib.error.HTTPError).
- Audio workers are capped at two, including forced previews. Worker-start
  failures release capacity; a close/spawn race terminates and reaps the new
  process. Operational sounds remain advisory, not guaranteed alarm delivery.
- Runtime configuration (4 MiB), connector definitions (2 MiB) and recovery state
  (32 MiB) are bounded before JSON parsing. Duplicate keys, non-finite numbers,
  excessive nesting and non-object recovery documents fail closed. Configuration
  and state writes enforce the corresponding read limit, including the final
  newline. These limits are defensive ceilings, not capacity promises.
- Runtime JSON readers check the opened file descriptor, reject nonregular files,
  hard links and final symlinks, and use nonblocking opens to avoid named-pipe
  hangs. Private-file permission repair occurs only after these checks. Connector
  discovery may resolve a same-directory alias first; out-of-directory targets
  are excluded. Parent directories remain part of the trusted OS/install boundary.
  An unsafe `.active_connector` marker is ignored using bounded reads; Settings
  credentials reject hard links before changing permissions. These controls follow
  [Python's JSON input resource warning](https://docs.python.org/3/library/json.html).
- The v1.2.0 delivery journal stores allow-listed semantic operations, not URLs,
  authorization headers or connector credentials. Entries retain their original
  connection binding and asset/location context. Uncertain unsafe writes require
  password-authorized, attributed review rather than automatic replay. Pending
  lifecycle work is not evicted on capacity overflow. See [delivery boundaries](offline-delivery.md).
- Cached team lists contain only IDs and display names, not arbitrary directory
  payloads. They are operational personal data in the owner-private state file,
  subject to the site's access, backup and privacy policy; they are not proof of
  identity or permission to work on a machine.
- CI actions use full upstream commit IDs and do not persist checkout credentials.
  Dependabot remains enabled for reviewed updates. This follows the
  [GitHub Actions secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use).
- Staged update manifests and signatures survive restarts. The application
  reauthenticates them and re-hashes the executable before promotion; unsigned
  display summaries do not grant update authority.
- Remote error JSON may be an object, array, scalar or null. Diagnostics retain
  HTTP status without crashing on these shapes, redact known authentication values
  and strip terminal control bytes. Remote diagnostics remain untrusted text.
  Redaction includes resolved literal authentication fields, authorization tokens
  without their scheme prefix, and URL-encoded credential forms. Store secrets in
  the documented credentials/authentication sections, never in business fields.
- `FLOORTERMINAL_DISABLE_NETWORK=1` blocks the real connector and update HTTP
  transports during offline review. `FLOORTERMINAL_DISABLE_UPDATE_NETWORK=1`
  additionally remains supported for update-only isolation. These flags disable
  networking; they cannot select another host or bypass signature checks.
- The distribution integrity checks verify source/version/signature agreement and optionally
  audits bounded archives without extracting or executing them. It complements,
  rather than replaces, secret scanning and code review.

## Deployment requirements

- Run under a dedicated, unprivileged operating-system account.
- Change the public initial Settings password `admin@123` before production.
  Protect and back up `settings_auth.json`; it stores only a salted verifier and
  takes precedence over build credentials. Damaged local credentials block
  administrator access without interrupting operator reporting. See
  [Settings access](settings-access.md). This is not a privileged OS security boundary.
- Restrict physical access and disable unused desktop/session services.
- Store connector files as mode `0600`; rotate credentials after suspected access.
- Allow outbound network access only to required connector hosts and trusted DNS.
- Keep Raspberry Pi OS, firmware, Python/build tooling, and dependencies patched.
- Back up and periodically restore-test state and audit logs.
- Preserve the owner-private `records/incidents.sqlite3` reporting archive too.
  It contains operational names and notes, not connector secrets. It is not
  encrypted by the app; apply the site's disk/backup access and privacy policy.
  Use a stopped application or SQLite's backup facility for consistent copies.
  See [local history security and retention](local-history.md).
- Validate time synchronization, storage alarms, retention, and connector rate limits.
- Treat the application as reporting/coordination software—not a PLC, interlock,
  emergency stop, machine guard, or lockout/tagout control.
- Rotate credentials after suspected exposure. Deleting a credential from a file
  does not revoke it on the external system.
- Update verification requires only the public trust anchor embedded in the
  executable. A terminal, connector file, or update drive must never contain a
  release-signing private key. See the [trust model](threat-model.md).
- Treat update drives as controlled media: label them, store them with the release
  record, and verify the published archive digest before preparing one.

## Verification limits

Passing unit tests, lint, CodeQL, or dependency scans reduces known risk but cannot
prove absence of defects. Industrial standards such as IEC 62443, ISO 27001, and
functional-safety standards apply to systems, organizations, and assessed life
cycles; this repository does not claim conformity or certification.
