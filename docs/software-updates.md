# Offline software updates

This document specifies the software-update subsystem: what it guarantees, how it is
built, what it refuses, how it fails, and how update integrity is verified. The operator-facing procedure is in the
[step-by-step update guide](update-user-guide.md).

## 1. Scope

The subsystem does three things and nothing else:

1. tells an operator which version is running and what that version contains;
2. tells an operator whether a newer version has been published, when the terminal
   is able to find out;
3. installs a version that arrived on removable media, after an administrator
   authorizes it, and can put the previous one back.

It is explicitly **not** an automatic updater. The terminal never downloads
software, never installs without attributed human authorization, and never executes
anything that arrived on removable media.

### Non-goals

- No background or scheduled installation.
- No remote administration, push, or management channel.
- No partial, differential, or streaming updates.
- No update of the operating system, firmware, or any package outside the
  application's own version slot.
- No change to deployment-owned data of any kind.

### Independence from production

The update subsystem is additive. Reporting, timers, state recovery, the connector,
Settings, sound, the kiosk lifecycle, and audit logging behave identically whether
the indicator is green, amber, or red, whether the update directories exist, and
whether the subsystem started at all. Construction failure is caught and logged as
`update_subsystem_unavailable`; the panel then reports an unavailable status and the
console runs normally.

## 2. Trust model

| Property | Mechanism |
|---|---|
| Only the maintainer can author an update | Detached Ed25519 signature over the exact manifest bytes, verified with public keys compiled into the running build |
| The payload is exactly what was signed | SHA-256 of the executable is carried in the signed manifest and verified on the medium, again while copying, and again from the terminal's own disk |
| The update source cannot be redirected | The endpoint, host, product identity, accepted volume labels, and trusted keys are source constants; no configuration, environment variable, or file can change them |
| Removable media cannot execute code | Nothing on the medium is ever executed, sourced, or evaluated; it is read as size-bounded data through paths that refuse symbolic links |
| A person is accountable for every change | Administrator identity plus the PBKDF2 Settings password, recorded in the update log and the activity log |
| A bad version cannot strand a terminal | Version slots, an atomic link switch, a supervised boot counter, automatic rollback, and one-touch manual rollback |
| Evidence survives the change | Append-only update log on the terminal and a mirrored copy on the medium |

### What is out of scope

Compromise of the maintainer's offline private key, of a privileged operating-system
account on the terminal, of the Raspberry Pi firmware or bootloader, or physical
substitution of storage is outside this boundary — as it is for the rest of the
product. See [threat model](threat-model.md).

### Cryptography

`update/signing.py` is a self-contained implementation of Ed25519 as specified in
[RFC 8032](https://www.rfc-editor.org/rfc/rfc8032). The project carries no runtime
dependencies, so the algorithm is implemented rather than imported, and
`tests/unit/test_update_signing.py` checks it against the official RFC 8032 §7.1
test vectors plus tampering, truncation, unreduced-scalar, and invalid-point cases.

Only `verify` runs on a terminal. It processes public values exclusively, so the
absence of constant-time field arithmetic is not a key-recovery exposure. `sign` is
used exclusively by maintainer tooling on an offline workstation.

Verification costs a few milliseconds and runs on a background daemon thread, never
on the Tk event loop.

## 3. Installed layout

An installation made by the current `install.sh` is *managed*:

```text
/opt/floorterminal/
├── floorterminal          symlink → versions/<active>/floorterminal
├── bin/floorterminal-launch                 supervised launcher and boot watchdog
├── versions/
│   ├── 1.0.0/floorterminal + LICENSE, notices, SBOM, VERSION
│   └── 1.1.0/floorterminal + release.json
├── update/
│   ├── boot_state                 launcher-readable activation state (KEY=VALUE)
│   ├── journal.json               full activation history for the panel
│   ├── update-log.jsonl           append-only operator- and auditor-visible log
│   ├── channel_cache.json         last availability answer
│   └── staging/<version>/         verified candidate awaiting authorization
├── config.json  connector.json    deployment owned — never touched by an update
├── response_state.json            deployment owned — never touched by an update
└── logs/YYYY/MM/DD/activity.jsonl deployment owned — never touched by an update
```

Switching versions replaces exactly one symbolic link. `rename(2)` is atomic on
POSIX, so at every instant the link resolves to a complete executable.

The launcher exports `FLOORTERMINAL_HOME` so the application's runtime root
is the deployment root rather than the version slot. `update/layout.py` additionally
recognises the `versions/<version>/<executable>` shape directly, so configuration
never migrates into a slot even if the launcher is bypassed.

`install.sh` deploys to `/opt/floorterminal`. It honours
`FLOORTERMINAL_INSTALL_ROOT` so the offline test suite can execute the real
script against a sandbox and so staged deployment tooling can build an image root;
the value is read from the environment of the administrator who is already invoking
the installer, so it grants no privilege that person does not already have. The
running application never reads it.

An installation whose `floorterminal` is a regular file rather than a
symbolic link is *unmanaged*. It reports status normally and offers no in-place
version change; re-running the current `install.sh` migrates it, preserving the
previous executable under `update/replaced-executable-<timestamp>` as evidence.

## 4. Update package format

### Drive layout

```text
<volume labelled FLOORTERM>/
└── floorterminal-update/
    ├── update_manifest.json        signed metadata
    ├── update_manifest.json.sig    detached Ed25519 signature
    ├── floorterminal       the executable
    ├── SHA256SUMS                  convenience digests for human inspection
    └── READ_ME_FIRST.txt           plain-language instructions
```

Accepted volume labels are `FLOORTERM`, `FLOOR-TERM`, `FTERM_UPD`, and
`FT_UPDATE`. The primary label is at most eleven characters because FAT32
and exFAT cannot store a longer one. The `update-log/` directory is created on the
medium by the terminal.

### `update_manifest.json`

```json
{
  "schema_version": 1,
  "document_type": "update_package",
  "product_id": "floorterminal",
  "target": "linux/aarch64",
  "release": {
    "version": "1.1.0",
    "released_utc": "2026-11-14T09:00:00Z",
    "release_title": "Faster startup, clearer sync, safer offline updates",
    "release_summary": "One paragraph an operator can act on.",
    "minimum_upgradable_version": "1.0.0",
    "artifact": {
      "name": "floorterminal",
      "sha256": "<64 lowercase hex characters>",
      "size_bytes": 13755320
    },
    "notes_url": "https://github.com/thesohampatel/floorterminal/releases/tag/v1.1.0",
    "features": ["…"],
    "fixes": ["…"],
    "security": ["…"]
  }
}
```

### `update_manifest.json.sig`

```json
{
  "schema_version": 1,
  "algorithm": "ed25519",
  "key_id": "ba1b79d27fddd67a",
  "signature": "<base64 of 64 signature bytes>"
}
```

The signed message is the **exact byte content** of `update_manifest.json`. No
canonical re-serialization is involved, so no edit — including whitespace — can
survive verification.

### Parsing rules

`update/manifest.py` is fail-closed. It rejects, rather than ignores:

- a document larger than 64 KiB, not UTF-8, or not JSON;
- any unknown key at any level;
- a `schema_version`, `document_type`, `product_id`, or `target` this build does not
  accept;
- a version, minimum-upgrade floor, or timestamp that is not exactly well formed;
- an artifact name other than `floorterminal`;
- a digest that is not 64 lowercase hexadecimal characters;
- a size outside 1 MiB – 512 MiB;
- text fields over their length limits or containing control characters;
- more than 24 change entries, or an entry over 160 characters;
- a `notes_url` outside the official repository;
- a signature envelope naming another algorithm, a malformed key id, or a key this
  build does not trust.

### Version identifiers

`MAJOR.MINOR.PATCH`, optionally `-rc.N`, each component at most four digits. Build
metadata, leading-zero aliases, and arbitrary pre-release chains are unsupported.
Ordering is numerical: 1.10.0 is newer than 1.9.0. Stable terminals reject release
candidates; an already-candidate terminal may accept a newer candidate or final release.

## 5. Availability check

Optional, advisory, and incapable of delivering software.

| Property | Value |
|---|---|
| URL | `https://raw.githubusercontent.com/thesohampatel/floorterminal/main/update-channel/latest.json` (and `.sig`) |
| Host policy | Exact hostname match; any other host or scheme is refused before a socket is opened |
| Redirects | Refused |
| TLS | Verified certificate and hostname, TLS 1.2 minimum |
| Timeout | 6 s |
| Response bound | 64 KiB |
| Credentials | None sent; no cookies; one fixed `User-Agent` |
| Interval | Every 6 h on success, 30 min after a failure |
| Freshness | A cached answer older than 14 days is reported as stale |
| Signature | Required, using the same trusted keys as an update package |
| Failure | Reported as a red indicator; never raised, never retried tightly, never blocking |

`update-channel/latest.json` is a `update_channel` document: the same `release`
object plus `published_utc`, `targets`, and an `archive` naming the published GitHub
asset and its digest. Because it is signed, a compromised host or CDN cannot even
make a terminal *display* a version that the maintainer did not publish.

The exact signed document and signature are cached at `update/channel_cache.json`
and reauthenticated after restart. Editable display fields cannot substitute for
signed evidence; unsigned legacy summaries are ignored. Older announcements and
same-version executable/archive substitutions cannot replace the last verified
answer. A stale or failed refresh is shown explicitly, even when a newer release
was previously known. Turning the check off in Settings changes only whether the
terminal opens a connection; it cannot change where the terminal would look.

## 6. Detection, verification, staging

A background daemon thread polls the mount roots `/media`, `/run/media`, `/mnt`, and
`/Volumes` every six seconds, one and two levels deep, which covers the
`/media/<user>/<LABEL>` layout used by a Raspberry Pi OS desktop session.

Automatic detection requires an accepted volume label. **Scan USB drive** in the
panel additionally inspects every removable mount regardless of label, for a drive
whose filesystem could not keep one.

For a candidate:

1. Refuse the package directory, manifest, signature, and artifact if any of them is
   a symbolic link.
2. Read the manifest and signature under their size bounds.
3. Verify the signature, then parse the manifest.
4. Stream the artifact through SHA-256 and compare size and digest to the manifest.
   A mismatch is reported as a **rejected medium**, and nothing is copied.
5. Reject a version that is not newer than the installed one, or whose
   `minimum_upgradable_version` is above the installed one.
6. Check free space against the artifact size plus a 256 MiB reserve.
7. Copy with a size bound into a private `.copy-*` workspace, `fsync`, and verify
   the written payload before atomically renaming it to `update/staging/<version>/`.
8. On a Linux terminal, confirm the executable is ELF64 little-endian ARM64.
9. Retain the exact signed manifest and detached signature as owner-only files,
   alongside the display-only `release.json` summary. Keep the executable mode
   `0700`. Reauthenticate and re-hash the persisted package.

On restart and subsequent scans, local staging is rechecked before it is shown as
verified. Corrupt or unsigned staging is rejected with instructions to reinsert a
verified drive; a hand-written summary cannot authorize installation. A previously
staged pre-release copy without signed evidence must be staged again.

Failed copies remove only their temporary workspace; earlier valid candidates stay
usable. Interrupted copy workspaces are discarded at startup. After a replacement
is verified, superseded staging slots are removed to bound storage use. No running
version or deployment-owned data is modified by staging.

The executable and signed evidence move together, so an interrupted promotion
cannot leave an apparently complete executable without its verification files.

Staging is automatic because it is inert; **installation is not**, because it
restarts a production terminal.

## 7. Authorization

Installation and rollback reuse the existing protected-control flow: administrator
name, then the PBKDF2 Settings password, with the persistent failure throttle. New
purposes are `software_update` and `software_rollback`. Approval names the selected
version and binds installation to its exact executable digest. If background
discovery changes the candidate while the prompt is open, the action is refused
and the administrator must review and authorize the new selection.

If the line is not `RUNNING`, the password prompt states the current status and that
the terminal will restart and resume the event. Both the request and the outcome are
audited with the machine status at the time.

An action is refused while another operation is in flight, when nothing is staged,
when no rollback target exists, or when the installation is unmanaged.

## 8. Activation and probation

```text
confirmed ──activate──▶ probation ──dwell 120 s──▶ confirmed
                            │
                            ├── 3 failed supervised starts ──▶ rolled_back (launcher)
                            └── operator rollback ───────────▶ confirmed (previous)
```

Activation order is deliberate:

1. Verify the retained signature, version, complete executable size and checksum
   again. A retained target executable must also match that authenticated payload.
   Promote the complete staging directory, including signed evidence, into
   `versions/<version>/` with an atomic same-filesystem rename, then `fsync` the
   slot and versions directory. No active link or journal intent changes on a
   verification failure.
2. Write `journal.json` and `boot_state` recording the intent — **before** the
   switch.
3. Replace the active link atomically and `fsync` the deployment root.
4. Append to the update log and mirror the event onto the medium.
5. Restart: exit cleanly under a service manager, or `execv` the active link when
   frozen and unsupervised.

Because the journal is written first, a crash between steps 2 and 3 leaves a
probation record whose rollback target is the version that is still active — which
resolves to no change at all.

`bin/floorterminal-launch` runs before the application at every supervised start. While the
state is `probation` it increments the counter; once the counter exceeds the limit
it restores the previous slot with an atomic rename, records
`update_watchdog_rollback`, and starts the previous version. `Restart=always` with
`RestartSec=5` supplies the retries, and `StartLimitBurst=10` in 120 s comfortably
exceeds the three permitted attempts.

The launcher is POSIX `sh`. It never uses `eval`, `source`, or command substitution
on file content: each field is read with a plain `read` loop and validated against a
strict character class, so a damaged or hostile state file degrades to "start
normally". Every failure path still reaches the application.

A healthy version marks itself `confirmed` after 120 s of uninterrupted running,
which also prunes superseded slots down to three, never removing the active version
or the rollback target. Another upgrade is blocked during probation and while a
version switch still needs a restart. Only the process actually running the active
version may confirm its health; an older process cannot confirm a newly selected slot.

## 9. Failure analysis

| Interruption or fault | Result |
|---|---|
| Power loss while staging | Incomplete staging discarded on the next scan; running version untouched |
| Drive removed while staging | Copy fails, staging removed, medium reported as rejected |
| Power loss between the journal write and the link switch | Old version still active; recorded intent resolves to no change |
| Power loss during the link switch | `rename(2)` is atomic: either the old or the new link, never a partial one |
| Power loss immediately after the switch | New version starts on probation; if it cannot start, the watchdog restores the previous one |
| New version crashes on start | Restored automatically after three supervised attempts; red indicator explains why |
| New version starts but is unwanted | One-touch **RESTORE VERSION**, administrator authorized |
| `journal.json` corrupted | Treated as unknown; the active link is left exactly as it is and the terminal starts |
| `boot_state` corrupted or missing | Launcher validates every field, ignores what it cannot parse, and starts the active version |
| Update directory missing or read-only | Status reports unavailable; the console runs normally |
| Filesystem full | Staging refused with the required and available space; nothing changed |
| Network blocked or absent | Red indicator; every other function unaffected; USB updates still work |
| Signing key retired or lost | Installed software keeps running and rollback keeps working; no new packages can be published until a replacement key is rolled out |
| Update drive tampered with | Rejected before anything is copied; the reason is shown and logged both places |

The invariant behind the table: **the version the site last accepted is never
modified or removed while it can still be needed.**

## 10. Evidence

| Record | Location | Content |
|---|---|---|
| Update log | `update/update-log.jsonl` (mode 600, rotated at 2 MiB) | staged, activated, confirmed, rolled back, auto-rolled back, pruned, rejected media |
| Activity log | `logs/YYYY/MM/DD/activity.jsonl` | the same events in the console's normal audit stream, with administrator attribution |
| Medium log | `<drive>/update-log/<terminal>.jsonl` | what this drive did at each terminal it visited |
| Panel history | `update/journal.json`, last 40 entries | shown on the **Update activity** tab |
| Launcher record | `update/update-log.jsonl` | `update_watchdog_rollback`, written before the application starts |

## 11. Configuration surface

One key only:

```json
"software_update_check_enabled": true
```

Boolean, validated at startup and in Settings, default `true`. It controls **only**
whether the terminal opens a network connection to the fixed endpoint. It cannot
change the endpoint, the trusted keys, the accepted labels, the product identity, or
any safety bound — all of which are source constants in
`src/floorterminal/update/trust.py` and therefore fixed at build time.

`tests/unit/test_update_deployment.py` asserts that this is the only update-related
configuration key.

## 12. Standards alignment

The design follows the patterns that industrial update guidance expects, and claims
no certification:

- **Signed, verified, and version-identified artifacts** — NIST SP 800-218 (SSDF)
  PS.2, PS.3, PW.4 provenance and integrity practices.
- **Secure update, rollback, and defect management** — IEC 62443-4-1 practices SM-7,
  SM-9, SM-10, SM-11 as design guidance for update delivery, patch management, and
  product end-of-life.
- **Fail-safe activation with automatic recovery** — the A/B slot and boot-counter
  pattern used by embedded update frameworks, so an unattended terminal cannot be
  left unbootable.
- **Attributed authorization and tamper-evident records** — the same PBKDF2
  administrator control and append-only audit stream the rest of the product uses.

The residual responsibilities in [industrial deployment](industrial-deployment.md)
apply unchanged: site change control, validation of each release in a controlled
environment before production, physical access control, media handling policy, and
approval by the accountable system owner.

## 13. Verification

Offline tests covering this subsystem live in:

```text
tests/unit/test_update_signing.py       RFC 8032 vectors and tampering
tests/unit/test_update_manifest.py      schema strictness and signature binding
tests/unit/test_update_media.py         discovery, verification, staging, symlink refusal
tests/unit/test_update_installer.py     activation, rollback, watchdog, interruption
tests/unit/test_update_service.py       status classification and safe failure
tests/unit/test_update_launcher.py      the shell watchdog, run as a real process
tests/unit/test_update_deployment.py    immutable policy, installer, service, pipeline
tests/unit/test_update_installer_script.py  the real install.sh, run in a sandbox
tests/unit/test_update_application.py   panel drawing, controls, and authorization
```

None of them opens a socket. Run the whole suite with:

```bash
FLOORTERMINAL_DISABLE_NETWORK=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Passing tests reduce known risk and do not prove the absence of defects. Complete
site acceptance before deploying any release.
