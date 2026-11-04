# Updates without losing connector or configuration data

This describes the **v1.2.0** safeguards. It is not a claim that
already-installed older executables contain these new checks.

## What the operator does

1. Finish active responses in every group and wait for saved updates to synchronize.
   Resolve held deliveries first. Do not discard reports just to enable an update.
2. Insert the signed update USB drive and open **Software Update**.
3. Authorize **Install** or **Restore** with the administrator identity/password.
4. The kiosk validates its saved data, creates a private local checkpoint, verifies
   compatibility and switches versions. Progress remains visible; this work runs
   outside the animation thread.
5. Allow the new version's two-minute health check to finish before restarting
   normal reporting. Settings/reporting writes are temporarily held during this
   planned maintenance period. Update information and authorized Restore remain
   available. Confirmation requires a recent healthy GUI heartbeat, not merely a
   background thread that is still alive.

A refusal leaves the running executable selected and the data intact. Read the
reason, correct that condition, and try again. No manual connector replacement is
needed for a compatible schema-1 connector.

## What happens to each file

| Data | Upgrade / downgrade behavior |
| --- | --- |
| `connector.json` and other detected connector files | Validated as data; copied byte-for-byte into a private checkpoint; originals are not rewritten. Credentials, custom mappings, optional features and unrecognized extension data remain present. |
| `.active_connector` | Preserved. A selection naming a missing file blocks the change instead of silently selecting a different system. |
| `config.json` | Known defaults and the legacy directory-page alias are adapted in memory. Settings saves preserve unknown top-level extensions already in the file. A future unsupported schema is rejected, not reset. |
| Configuration extensions dropped by an older Settings writer | Before an allowed downgrade to 1.0/1.1, keys that writer cannot retain are saved privately. On return, only **missing** keys are merged and validated, then saved atomically. Present values and edits made while downgraded win. |
| `response_state.json` | Validated and checkpointed for investigation, **never restored from a historical snapshot automatically**. Restoring old state could resurrect completed work or resend already delivered messages. |
| Settings password, authentication throttle, history database and logs | Left in place. They are not replaced by defaults, reset, or rolled back by this subsystem. Checkpoints are not a full installation backup. |

Schema version and application version are different things. Application 1.2.0
continues to read connector `schema_version: 1`, contract version `1.0`, and state
schema 1. Do **not** change those numbers to match the application release.

## Safe backward compatibility, not guessed compatibility

An older executable cannot implement features that did not exist when it was
built. The console therefore refuses a downgrade that would silently lose behavior.
Known examples include independent station groups, local-only reporting, a custom
request budget the older version cannot honor, qualified messaging recipients,
new nested mappings, per-operation directory limits, path idempotency, or
hold-on-uncertainty delivery policies.
Others-only or more-than-four custom failure catalogues also refuse downgrade to
the old fixed-count readers. New keyed team/user assignment mappings,
`failure_details` and `location_ids` mappings are refused when an older executable
would ignore them. These are feature checks, not destructive catalogue truncation
or connector rewriting. Existing one-to-four lists and legacy assignment objects
remain readable by the new version without manual conversion.

Legacy state readers reject newer fields, including the cached team directory and
its durable `roster_refresh` retry metadata. Their
presence can block a downgrade even after production resumes. The kiosk does not
delete those fields to force a successful-looking downgrade. Keep the current
version or use a release with a reviewed lossless migration. Live incidents and
unresolved queues always block an operator-requested version change.

Forward compatibility is also checked, not assumed. For a different version at or
after 1.2.0, the authenticated local candidate must successfully validate a detached
copy using the headless compatibility protocol before activation. Failure, timeout,
unsupported format or a mismatching result keeps the running version selected.
This cannot verify external account permissions or guarantee compatibility with
arbitrary future software. Normal connector commissioning still applies.

No migration guesses a new endpoint, credential, enum, identifier, remote field
meaning or idempotency guarantee. If an external service changes its API, an
authorized integrator may still need to update the connector deliberately.

## Private checkpoints and recovery

Checkpoints are under:

```text
<installation>/update/data-checkpoints/change-<random>/
    config.json
    connector.json                  # plus every other detected connector
    .active_connector               # if present
    response_state.json              # if present
    checkpoint.json                  # versions, time and file digests
```

Directories use owner-only permissions (0700), and files use 0600. Connector copies
contain credentials if the originals do. They are **not encrypted**: protect the
device account/storage and do not upload the update directory to GitHub, support
tickets, shared drives or the USB update medium. Only ordinary update event
metadata is mirrored to USB; no checkpoint contents or credentials are mirrored.

At most three recent checkpoints are retained. Preparation reserves 256 MiB of free
space in addition to the bounded data copy; insufficient space refuses the change.
Files are bounded, regular-file-only, and checked for links. Directory persistence
is flushed before activation. Checkpoints are rechecked against the live files
before the version switch; concurrent edits require a retry.

`update/config-carry.json` is a private, bounded recovery record used only for
configuration extensions an older Settings writer would drop. A successful
validated merge retires it. A failed save retains it for retry. It never contains
instructions to restore a connector or operational queue.

Do not copy an entire checkpoint over a running installation. In particular,
restoring old credentials can undo a rotation, and restoring old operational state
can duplicate external writes. Recovery beyond the automatic missing-key merge is
an administrator-reviewed action with the application stopped and the external
records reconciled.

## Compatibility protocol for developers

`floorterminal --check-update-data` runs before Tk creates a window. It reads the
deployment root selected by `FLOORTERMINAL_HOME`, performs local validation and
prints a small JSON result: protocol 1, its own application version, a Boolean
`compatible`, a content fingerprint, and the connector count on success. Exit 0
means local validation succeeded; exit 78 means it did not. No file is modified and
no external call is made.

The parent invokes only a signature/checksum-verified candidate copied to terminal
storage, and only after administrator authorization. It supplies a private detached
checkpoint as HOME/runtime root, no inherited API credentials, and
`FLOORTERMINAL_DISABLE_NETWORK=1`. Runtime is bounded to 30 seconds and accepted
output to 64 KiB; child diagnostics are not copied into operator logs. The result
must name the selected version and match the original data fingerprint; a candidate
that rewrites its input is refused. This is a trusted-code protocol, not an OS
sandbox against a malicious maintainer-signed executable.

Future releases must retain this protocol, implement reviewed readers/adapters for
supported earlier schemas, and test round trips. A destructive migration requires
an explicit new transactional design; changing a schema number or relaxing
validation is not a migration. Never claim arbitrary forward/backward compatibility
just because JSON parsed successfully.

## First upgrade from a published older version

The source safeguards cannot retroactively change the 1.0/1.1 updater. Before its
first upgrade, schedule an idle, fully synchronized maintenance window and retain a
secure site backup. A new supervised probationary startup validates runtime data
and refuses active responses or pending deliveries before entering the normal GUI
or migrating legacy state. Invalid configuration/state requests supervised
recovery instead of sitting indefinitely on a configuration error page. The
existing launcher then retries and can restore its previous slot.

The update USB remains the existing signed format; no connector credentials belong
on it. This change does not require editing the signed manifest or its schema.

See [operator update steps](update-user-guide.md), [technical update design](software-updates.md),
[connector commissioning](connector-commissioning.md) and [verification evidence](verification.md).

For opt-in native acceptance on a spare Pi, run
`python3 tests/unit/update_binary_driver.py --executable /path/to/test/floorterminal`.
It creates and removes a disposable managed tree, signs only with a throwaway
in-memory test key, and exercises the real candidate's headless reader,
activation, rollback and config-extension return. Its old slot is a fixture, not
a certification of an older compiled release. Never point normal GUI automation
at a production runtime directory.
