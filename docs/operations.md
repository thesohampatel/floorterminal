# Operations and response controls

## Sound commissioning

Operational cues supplement the visible status and guidance. Configure enablement,
volume, and repeat cooldown in protected Settings, then use **Test sound** under the
actual kiosk account and output device. Playback failure never changes workflow
state. Do not treat a cue as a safety alarm or external-sync acknowledgement. See
[sound and accessibility](sound.md).

## Reporting downtime

Select at least one station or the entire line. Failure presets remain optional. If **Others** is selected, an optional short note appears on the same touchscreen keyboard; skipping it never blocks a report. Touch **Report a Problem**, then use the single deliberate **YES, LINE IS DOWN** confirmation.

The terminal records DOWN locally before network work. **SYNC PENDING** remains visible and can be touched for an immediate attempt. Background attempts occur no more than once per minute, reuse the same idempotency key, and log attempt two and later distinctly.

## Starting planned work

Planned work (Preventive Maintenance / Modification) is recorded locally even when the connector is unavailable, with the same idempotency discipline before any response record is created. The terminal freezes the selected stations, failure details, operator, available participants, title, and description with that event. If the roster cannot be fetched offline, the event is queued as not yet assigned and the crew can be selected after synchronization. Until synchronization succeeds, station selection and a second report/planned-work start are blocked so one physical event cannot be mixed with another. If the response is lost or ambiguous, automatic and manual attempts reuse the exact same key. The line remains RUNNING locally until a usable remote response-record ID arrives.

## Asset state synchronization

When configured, OFFLINE/ONLINE asset-state creation is also persisted before transmission and uses its own stable idempotency key. A timeout therefore retries the same external event instead of creating another status record. An asset-enabled connector is rejected unless its mapped create operation declares a remotely enforced idempotency mechanism. A deployment acceptance test must still prove the external service or gateway actually honors that declaration.

## Escalation

`escalation_minutes` accepts 0–1440; 0 disables escalation. At the threshold, DOWN is escalated once. If `escalation_chat_name` is set, only that destination is used; otherwise Engineering and common-activity destinations are used. Without messaging capability, the on-screen escalated state and audit record still appear. Repair start clears escalation immediately.

Choose a conservative threshold to avoid alert fatigue and verify escalation routing during deployment acceptance.

## Engineering roster

The roster is sorted by local selection frequency and then alphabetically. **Search Names** filters the already-fetched roster locally and never makes another external request. Filtering never clears selections. Reopen the crew control to add or remove engineers during active work.

## Completion and analysis

`micro_stop_threshold_minutes` accepts 1–1440. A completed event at or below the threshold is `MICRO-STOP`; a longer event is `DOWNTIME EVENT`. The classification, raw duration, and configured threshold are written to structured logs and lifecycle details.

## Accessibility and language

Measured touch-target sizes, contrast ratios, and the rules enforced by tests are
recorded in [accessibility evidence](accessibility.md), together with the two open
commissioning decisions: glove suitability on a 7-inch panel, and darkening small
coloured text.

Status is represented by words, animated faces, colors, station glyphs, product motion, process lamps, and conveyor/motor movement. Mechanical motion occurs only while Production is running; stopped motion is therefore operational information, not decoration. Button symbols are vector-drawn where possible so they do not depend on platform emoji fonts. Select `colorblind_safe` in Settings for the blue/amber palette. Locale catalogs live under `floorterminal/i18n`; English is guaranteed fallback. Add a complete JSON catalog at build time and select its filename stem through `ui_language`. Test translated text on every supported resolution; right-to-left layout is not currently supported.

## Software updates

The update indicator beside the information control reports one of three states and
never affects production: green when the terminal runs the newest published version,
amber when an action is available or availability is uncertain, and red when
availability could not be checked or a version was recovered automatically.

Software is installed only from a USB drive labelled `FLOORTERM` carrying a
maintainer-signed package, and only after an administrator supplies an identity and
the Settings password. The terminal verifies the signature and checksum before
copying anything, keeps the previous version installed for one-touch rollback, and
restores it automatically when a newly activated version cannot start. Configuration,
connector files, saved workflow state, and audit logs are never touched, so the
terminal resumes the exact state it held before restarting.

`software_update_check_enabled` controls only whether the terminal opens a network
connection to the fixed release endpoint. Turn it off for air-gapped sites; the
endpoint, trusted signing keys, and accepted media identity are fixed at build time
and cannot be changed by configuration.

Operator procedure: [update guide](update-user-guide.md). Full specification,
formats, integrity checks, and failure analysis:
[offline software updates](software-updates.md).

## Software Information panel

The header information control opens one structured panel containing the embedded release version, immutable product/maintainer identity, support contact, distribution identity, MIT permissions, explicit exclusions, copyright condition, and deployment responsibilities. Safety, connector/system, and data/privacy responsibilities are separated for quick reading. These values come from the validated build identity and cannot be edited through runtime Settings.
