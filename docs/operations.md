# Operations and response controls

This guide describes v1.2.0. Older 1.1.0 terminals retain their
older synchronization behavior until a new release is installed.

## Sound commissioning

Operational cues supplement the visible status and guidance. Configure enablement,
volume, and repeat cooldown in protected Settings, then use **Test sound** under the
actual kiosk account and output device. Playback failure never changes workflow
state. Do not treat a cue as a safety alarm or external-sync acknowledgement. See
[sound and accessibility](sound.md).

## Reporting downtime

For independent cells, first commission [station groups](station-groups.md).
The main action controls affect the focused incident. A stopped group's timer
continues while another group is displayed; completing one does not release the
others. Confirm the impact preview before recording a stop. Whole-line reporting
cannot overlap unresolved group incidents.

Select at least one station or the entire line. Failure presets remain optional.
If **Others** is selected, an optional short note appears on the same touchscreen
keyboard; skipping it never blocks a report. In v1.2.0, use **Report • Engineering**
or **Start self-fix** directly on the station sheet. The main reporting control
also offers Engineering help or operator self-fix; the operator name remains
optional. See [the short touch paths](operator-touch-flow.md) for exact controls.

The terminal records DOWN and its delivery instructions locally before network
work. The queued-updates strip opens **Saved updates**. Delivery runs separately
from operator actions, respects the request budget and service delays, and reuses
stable idempotency keys. See [offline delivery and recovery](offline-delivery.md).

An operator self-fix starts directly in REPAIRING, with an operator-specific status
label and no Engineering call. If help becomes necessary, requesting Engineering
returns to DOWN without changing the incident or original downtime start. The same
record then follows normal repair and release. See [self-fix and handover](operator-self-fix.md).

## Starting planned work

Planned work enters ENGINEERING locally, with immutable station/failure details,
available participants and a stable event identifier. A remote record ID is not
required to start or complete the physical workflow. A cached crew list is usable
offline; if none exists, explicitly continue without names and update participation
later. Once the current incident is released, a new incident can be recorded even
if older delivery instructions remain queued. Each event retains its own identity.

## Asset state synchronization

Group asset IDs are declared in the connector's `workflow.group_targets`, not
in station display names. Partial group stops never implicitly target the
aggregate line asset. Shared external assets remain Offline until their last
affected group releases. Missing group mappings leave local reporting usable
but send no asset-state change. Review [mapping rules](station-groups.md#connector-mapping).

When configured, OFFLINE/ONLINE events are persisted before transmission, using
the original stop/confirmed release time rather than the later synchronization
time. The connector must declare real deduplication or an explicit hold-on-ambiguity
policy. Safe retries reuse the same event key; uncertain native append-only writes
remain held. An administrator can verify an existing asset event without resending
it. See [connector commissioning](connector-commissioning.md) and test these
semantics in an authorized non-production environment before deployment.

## Escalation

`escalation_minutes` accepts 0–1440; 0 disables escalation. At the threshold, DOWN is escalated once. If `escalation_chat_name` is set, only that destination is used; otherwise Engineering and common-activity destinations are used. Without messaging capability, the on-screen escalated state and audit record still appear. Repair start clears escalation immediately.

Choose a conservative threshold to avoid alert fatigue and verify escalation routing during deployment acceptance.
For operator self-fix, escalation waits until Engineering has actually been
requested, and uses that request time. Direct Engineering arrival is also allowed.

## Engineering roster

The roster is sorted by local selection frequency and then alphabetically. **Search Names** filters the already-fetched roster locally and never makes another external request. Filtering never clears selections. Reopen the crew control to add or remove engineers during active work.

Cached names show their age. One successful refresh per local day runs after
midnight when idle; **Settings → Connection → Refresh team members** requests an
earlier refresh. Opening/searching a saved roster makes no directory request.
See [daily roster policy and recovery](team-roster.md). Do not use a cached
selection as an authorization or attendance record. See [crew and connector
boundaries](offline-delivery.md#connector-changes-and-crew-selection).

## Completion and analysis

`micro_stop_threshold_minutes` accepts 1–1440. A completed event at or below the threshold is `MICRO-STOP`; a longer event is `DOWNTIME EVENT`. The classification, raw duration, and configured threshold are written to structured logs and lifecycle details.

The response category (operator self-fix, operator then Engineering, or Engineering)
is separate from this duration classification. An operator-only event can be long.

## Automatic device care

Disk space, bounded audit retention and available Linux health sensors are checked
in the background. Settings → System shows a read-only snapshot; operators do not
choose retention or reserve sizes. See [cleanup rules and limits](automatic-device-care.md).

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
