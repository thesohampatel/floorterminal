# Architecture

The project uses a layered, single-responsibility structure:

- `app.py`: application lifecycle — construction, startup, rendering cadence, the Tk event loop, and shutdown.
- `controller/`: the controller split into separately reviewable layers composed onto `FloorTerminalApp` — `workflow.py` (reporting, response, restoration, escalation, synchronization), `dialogs.py` (selection dialogs, on-screen keyboard, protected administrator access), and `updates.py` (the software-update controls). They are mixins so the split changes only how the code is organised for review, never how it behaves.
- `audio.py` and `assets/sounds/`: allow-listed asynchronous native playback and
  reproducibly generated original operational cues.
- `assets/branding/` and `branding/floorterminal/`: packaged runtime identity sizes
  and the original vector/raster brand master used by documentation and launchers.
- `ui/`: responsive canvas, touch view, protected modal Settings, dialogs, and `contrast.py`, which keeps control labels and small coloured text readable without flattening the palette's status separation.
- `i18n/`: packaged JSON locale catalogs, installed-locale discovery, and guaranteed English fallback.
- `core/`: validated runtime configuration, immutable build project profile, paths, and a system-clock plausibility check, since every recorded time depends on it.
- `update/`: offline software updates — RFC 8032 Ed25519 verification, strict signed-metadata parsing, removable-media discovery and staging, atomic version activation with supervised rollback, the optional availability check, and the embedded release catalog.
- `integration/definition.py`: strict Connector v1 parsing and validation.
- `integration/discovery.py`: bounded deployment-directory scanning, offline status inventory, deterministic automatic selection, and owner-only active selection state.
- `integration/runtime.py`: Connector v1 REST/RPC/OSLC/OData-style request construction, derived/header/query/body authentication, JSON/form envelopes, response extraction, declared safe retry, local request budget, transport, and normalized errors.
- `integration/workflow.py`: stable response-record, assignment, messaging, directory, and asset-status semantics.
- `services/`: narrow application-facing integration contract.
- `storage/`: atomic state and dated activity logs with retention/storage safeguards.

`FloorTerminalApp` never constructs a URL or authorization header. The workflow layer requests a semantic operation, the definition selects the external operation ID, and the runtime is the only network boundary. There is one configured integration per deployed terminal because one line-side terminal coordinates one authoritative maintenance workflow.

Source and embedded project profile are read-only. `config.json`, connector files, `.active_connector`, `response_state.json`, and dated logs are writable beside the executable. Frozen applications use the same deployment-root rule and never depend on the shell working directory.

Security boundaries include HTTPS-only enabled integrations, same-host request resolution, URL-encoded path values, query allow-lists, a maximum of ten app requests in a rolling minute, redacted audit events, unpredictable atomic owner-only integration writes, password-protected and administrator-attributed Settings/kiosk controls, build-time plaintext-password removal, bounded responses, supervised kiosk restart, strict state-integrity validation, and release audits that reject source/log/state leakage.

The update subsystem is additive and cannot affect production. It owns one daemon thread, publishes an immutable status snapshot under a lock, and never calls into Tk; the view reads that snapshot during its normal render pass. Construction failure, a damaged journal, an unreadable medium, and a blocked network are all reportable states rather than exceptions. Software arrives only on removable media carrying a detached Ed25519 signature made by a key compiled into the running build, is verified three times (on the medium, while copying, and from the terminal's disk after `fsync`), and is activated only after administrator identity and password authorization. Activation replaces one symbolic link, which `rename(2)` makes atomic, so the previously accepted version is never modified and always remains launchable. `bin/floorterminal-launch` counts supervised starts before the application runs and restores the previous slot automatically when a new version cannot start. Deployment-owned configuration, connectors, state, and logs are never read, moved, or rewritten by an update, so a terminal resumes the exact workflow state it held before restarting. See [offline software updates](software-updates.md).

Audio is deliberately outside the workflow's success criteria. Cue names are fixed,
asset paths cannot escape the packaged directory, native players receive argument
lists without a shell, and bounded daemon workers convert failures into sanitized
diagnostic events without blocking Tk or changing operational state.

Unplanned downtime is local-first: the terminal atomically persists `DOWN`, the original timestamp, selected station/failure snapshots, a stable report ID, and synchronization metadata before attempting response-record creation. The report ID is supplied on every attempt through the connector's required, remotely enforced idempotency mapping. A failed or unavailable integration leaves the timer active and unattended retry occurs at most once per minute with the same key. If the first response is lost after a remote commit, the external system must return the original response record for the repeated key instead of creating another. Only a response containing a usable remote ID clears the queue.

Starting planned work follows the identical pattern, including while offline: the terminal persists immutable station/failure snapshots, title, description, priority, participants, and a stable report ID under `pending_planned_work` before attempting response-record creation. Conflicting station changes and new workflow starts are blocked while it is queued. The line stays `RUNNING` locally until a response with a usable remote ID arrives; background and touch retries reuse the unchanged key.

Asset OFFLINE/ONLINE creation is a second independently recoverable operation. State
schema v1 persists its target, stable idempotency key, exact original request
context, and attempt count before the request. A timeout leaves these values intact,
and retry supplies the same key and byte-equivalent canonical values.
Asset-enabled connectors must map a remotely enforced idempotency mechanism for
`create_asset_status`, just as response-record-enabled connectors do for
`create_response_record`.

Persisted state is schema-versioned and type-checked. Invalid JSON, unknown statuses/fields, malformed timers, or invalid pending work stop startup and show a state-recovery screen. The original file is preserved and a CRITICAL audit event is attempted; the application never converts corrupt state into `RUNNING` automatically.

State schema v1 persists optional failure notes, engineer selection frequency,
escalation completion, synchronization timestamps/attempts, immutable queued-event
context, pending planned work, recoverable asset-status idempotency state, and
pending response-status/participant-assignment updates. Once a remote response
record exists, local repair, crew, and Production-release transitions are committed
before these non-create external updates. A network failure is displayed as queued
synchronization and retried at a bounded cadence; it cannot reverse the physical
line decision.
Settings credentials have their own installation-local storage boundary:
`core/settings_auth.py` reads the active verifier for each protected action.
The embedded build verifier is used only when no local credential file exists;
an invalid local file fails closed for administrator access, not operator workflow.
The three-stage touch password-change flow reauthorizes, confirms and atomically
stores a salted verifier outside signed version slots, so normal upgrades cannot
reset a site password. There is no permanent master override. See
[Settings access](settings-access.md).

Administrator identity is a separate password-authorized security event for protected
controls only; the application does not implement shift attendance or operator
check-in.

The DOWN response loop runs two bounded timers: store-and-forward tries at most once per minute with the same remotely idempotent report key; escalation checks every 30 seconds and fires once after `escalation_minutes`. Starting repair clears escalation immediately. Completion classifies duration using `micro_stop_threshold_minutes`; raw seconds and the threshold remain in the audit event for reproducible analysis.

Accessibility uses redundant state encoding: color, status face, text, and a station glyph. `ui_color_preset=colorblind_safe` supplies a blue/amber/orange/purple palette. Locale JSON is package data in source and native builds; missing keys/locales fall back to English. Fixed-coordinate translations still require visual acceptance testing on each target display, and right-to-left mirroring is not currently claimed.

The 800×480 logical canvas remains resolution-independent through uniform viewport
scaling and centered letterboxing. Rectangles, polygons, ovals, arcs, lines, image
positions, strokes, arrow shapes, text sizes, and text widths all use the same
transform. The line visualization derives every workcell from configured stations,
pages beyond eleven stations, and uses state-driven spindle, roller, drive-motor,
process-lamp, and product animation. The Information modal uses the same logical
bounds and separates immutable identity, license scope, exclusions, and operational
responsibility into fixed scan regions; neither screen relies on native emoji
rendering.
