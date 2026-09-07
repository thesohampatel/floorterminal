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
  remotely enforced idempotency for non-repeatable operations;
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

- CI actions use full upstream commit IDs and do not persist checkout credentials.
  Dependabot remains enabled for reviewed updates. This follows the
  [GitHub Actions secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use).
- Staged update manifests and signatures survive restarts. The application
  reauthenticates them and re-hashes the executable before promotion; unsigned
  display summaries do not grant update authority.
- Remote error JSON may be an object, array, scalar or null. Diagnostics retain
  HTTP status without crashing on these shapes, redact known authentication values
  and strip terminal control bytes. Remote diagnostics remain untrusted text.
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
