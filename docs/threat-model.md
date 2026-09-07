# Threat model

## Assets

Connector credentials, maintenance records, line status, response-record identifiers,
configuration, audit logs, and administrator access are protected assets.

Bundled sounds are non-secret immutable assets. Cue identifiers are allow-listed,
paths cannot escape the package directory, and native players are invoked without a
shell. Sound is not a safety control or trusted workflow confirmation.

## Trust boundaries

1. Touchscreen users and physical device access.
2. Local operating-system account and writable deployment directory.
3. Data-only connector contract and remote operations service.
4. Native build host, source repository, and distributed artifact.
5. Removable update media and the published availability channel.

## Principal threats and controls

| Threat | Primary controls | Residual responsibility |
|---|---|---|
| Unauthorized settings changes | PBKDF2 verifier, throttled unlock, attributed authorization | OS and physical access control |
| Credential disclosure | connector exclusion from builds, private modes, log redaction policy | secret storage and rotation |
| Duplicate remote records | durable event IDs and connector-declared remote idempotency | validate remote guarantee |
| Network interception or redirection | HTTPS, exact host policy, redirects disabled | trusted DNS/network and CA store |
| Corrupt or forged local state | strict schema validation, atomic writes, fail-closed startup | filesystem integrity and backups |
| Resource exhaustion | response limits, request budget, log retention, disk reserve | host monitoring and capacity |
| Malicious release or dependency | CI analysis, build audit, hashes, minimal dependencies | trusted distribution and signatures |
| Forged or altered software update | detached Ed25519 signature over exact metadata bytes verified against build-time keys, triple checksum verification, immutable product/target identity | offline custody of the signing key |
| Hostile removable media | nothing on the medium is executed, sourced, or evaluated; symlink-refusing bounded reads; hardcoded volume labels and package directory | physical media handling policy |
| Redirected update source | endpoint, host, and trust anchors are source constants; HTTPS with verified hostname and no redirects; signed channel document | trusted CA store and DNS |
| Unauthorized version change | administrator identity plus PBKDF2 password, refused while another operation runs, fully attributed in two logs | operating-system and physical access control |
| Update that cannot start | version slots, atomic link switch, supervised boot counter, automatic and one-touch rollback | site acceptance testing of each release |
| Kiosk escape or process termination | authenticated controls and systemd restart/sandbox | hardened OS session and physical security |
| Wall-clock correction | restart-restored deadlines are converted to monotonic process deadlines | reliable NTP remains required for audit timestamps |

Update-specific residual risk: an attacker holding the maintainer's offline signing
key, or with write access to the terminal's deployment directory as the kiosk
account, is already inside the boundary. The subsystem reduces neither, and weakens
nothing: that directory was already writable by that account before version slots
existed.

## Out of scope

The application does not directly control machinery and cannot establish machine
safety. Compromise of a privileged OS account, malicious firmware, a trusted CA,
or the configured remote service is outside the protection boundary.
