# Architecture

## Independent groups and local history (1.2.0)

`core/topology.py` validates a complete station partition and computes the
immutable impact snapshot before a report is accepted. `controller/groups.py`
coordinates incident focus and captured routing. `storage/incidents.py` keeps
the focused incident in the established workflow fields and parks other active
incidents alongside it. Delivery, crew cache and history staging are shared, not
duplicated per incident. There is one workflow/retry scheduler, not a timer or
network thread per group.

`ui/group_view.py` projects active incidents onto the station map and paginated
overview. `ui/group_settings.py` edits membership and stop propagation using the
existing kiosk form. A station cannot have overlapping active incidents. Group
IDs, routes and connector binding remain frozen until completion.

`storage/history.py` stages bounded snapshots within the same recovery commit,
then maintains the private, versioned SQLite archive. `services/history.py` runs
one background writer and acknowledges completed batches on the serialized local
operation worker; slow storage never executes in the animation loop. Remote
record IDs arriving after completion are reconciled separately. See
[group semantics](station-groups.md) and [storage boundaries](local-history.md).

## Variable station failure catalogues (1.2.0)

`core/config.py` validates one explicit custom-reason array per station, including
an empty array. Others is generated once by the controller. No fixed reason count
is imposed; the configuration, journal and state byte limits still apply.
`ui/failure_layout.py` computes only the visible touch cells from the viewport and
filtered indices. The selection set is independent of pagination/search. Opening
a saved selection uses set membership rather than repeated full-list searches.
`ui/failure_settings.py` reuses four editable rows over a complete Settings draft,
so catalogue size does not create an unbounded Tk widget tree.

The operator's reported stations and reasons remain distinct from indirectly
affected group members. Optional `failure_details` and `location_ids` mappings
carry structured data when explicitly supported by the remote schema. Creation
intents freeze this data; subsequent status/chat intents do not duplicate large
failure arrays unnecessarily. `integration/workflow.py` handles either declared
typed-ID or keyed-ID assignment objects uniformly at creation and crew changes.
Legacy downgrade checks reject unsupported catalogue sizes/mappings without
rewriting operator evidence. See [catalogue usage](failure-reasons.md).

## Application layers

In v1.2.2, `ui/content_cards.py` measures responsive information cards with
bounded touch-pagination fallback. `ui/delivery_view.py` owns the delivery centre;
`services/delivery.py` still owns expiry, retry, dispatch and acknowledgement.
New manual support calls bind to the current connector, separately from an older
incident's frozen routing. Message dismissal is administrator-protected, audited,
and limited to held chat notices. The journal schema and connector contract stay
unchanged. No additional runtime dependencies or animation timers are introduced.

For v1.2.1, `core/support.py` owns the validated three-slot manual
support configuration and resolves legacy defaults without changing incident or
automatic-notification routing. `ui/support_settings.py` edits those slots inside
the protected Settings draft; the workflow snapshots label/destination before
queuing the existing message operation. `ui/keyboard_layout.py` and the shared
`ui/layout.py` grid/header helpers are pure geometry, tested without a display.
`ui/information.py` separates identity/licensing/safety presentation from workflow
logic. No new network transport or runtime graphics dependency is introduced.

The project uses a layered, single-responsibility structure:

- `app.py`: application lifecycle — construction, startup, rendering cadence, the Tk event loop, and shutdown.
- `controller/`: the controller split into separately reviewable layers composed onto `FloorTerminalApp` — `workflow.py` (reporting, response, restoration, escalation, synchronization), `dialogs.py` (selection dialogs, on-screen keyboard, protected administrator access), and `updates.py` (the software-update controls). They are mixins so the split changes only how the code is organised for review, never how it behaves.
- `audio.py` and `assets/sounds/`: allow-listed asynchronous native playback and
  reproducibly generated original operational cues.
- `assets/branding/` and `branding/floorterminal/`: packaged runtime identity sizes
  and the original vector/raster brand master used by documentation and launchers.
- `ui/`: responsive canvas, touch view, protected modal Settings, dialogs, and `contrast.py`, which keeps control labels and small coloured text readable without flattening the palette's status separation.
- `ui/scene.py` retains canvas items, `ui/raster.py` bounds decoded image caching,
  and `ui/panels.py`/`ui/touch_button.py` provide app-owned pages and native,
  keyboard-accessible rounded buttons. See [rendering design](ui-performance.md).
- `i18n/`: packaged JSON locale catalogs, installed-locale discovery, and guaranteed English fallback.
- `core/`: validated runtime configuration, immutable build project profile, paths, and a system-clock plausibility check, since every recorded time depends on it.
- `core/rate_policy.py`: positive request-budget validation and a shared rolling
  request window. Active, diagnostic and older in-flight clients share its lock,
  timestamps and live policy; replacing a connector cannot reset or bypass it.
- `update/`: offline software updates — RFC 8032 Ed25519 verification, strict signed-metadata parsing, removable-media discovery and staging, atomic version activation with supervised rollback, the optional availability check, and the embedded release catalog.
- `integration/definition.py`: strict Connector v1 parsing and validation.
- `integration/discovery.py`: bounded deployment-directory scanning, offline status inventory, deterministic automatic selection, and owner-only active selection state.
- `integration/runtime.py`: Connector v1 REST/RPC/OSLC/OData-style request construction, derived/header/query/body authentication, JSON/form envelopes, response extraction, declared safe retry, local request budget, transport, and normalized errors.
- `integration/workflow.py`: stable response-record, assignment, messaging, directory, and asset-status semantics.
- `services/`: narrow application-facing integration contract.
- `services/delivery.py`: network-free workflow write facade, isolated single
  delivery worker, persistent acknowledgement/retry coordination and crew cache.
- `storage/delivery.py`: bounded semantic journal schema, immutable target context
  and local-to-remote record-reference resolution. It stores no connector secrets.
- `controller/operator.py`: operator-owned minor-stop response and same-incident
  Engineering handover, layered on the existing durable workflow.
- `storage/`: atomic incident state; bounded asynchronous audit writer and
  application-owned, adaptive log housekeeping (`housekeeping.py`).
- `services/health.py`: optional read-only Linux sensor observations; no Tk,
  network, process control or safety decisions.

`FloorTerminalApp` never constructs a URL or authorization header. The workflow layer requests a semantic operation, the definition selects the external operation ID, and the runtime is the only network boundary. There is one configured integration per deployed terminal because one line-side terminal coordinates one authoritative maintenance workflow.

Source and embedded project profile are read-only. `config.json`, connector files, `.active_connector`, `response_state.json`, and dated logs are writable beside the executable. Frozen applications use the same deployment-root rule and never depend on the shell working directory.

Security boundaries include HTTPS-only enabled integrations, same-host request resolution, URL-encoded path values, query allow-lists, a configurable shared app request budget in a rolling minute, redacted audit events, unpredictable atomic owner-only integration writes, password-protected and administrator-attributed Settings/kiosk controls, build-time plaintext-password removal, bounded responses, supervised kiosk restart, strict state-integrity validation, and release audits that reject source/log/state leakage.

Update discovery is independent of production. The background service publishes an
immutable status snapshot and never calls Tk. An authorized version change is a
separate maintenance operation: idle state, drained queues and no active workers
are required. `update/compatibility.py` validates runtime data, keeps private bounded
checkpoints and checks known legacy limits or a future candidate's headless reader.
Schema-1 connectors stay byte-identical; a missing-key config carry restores only
extensions an older Settings writer dropped. No historical state or credentials
are automatically restored. Hash/copy/probe work runs off the GUI thread; state is
saved before switching, not afterwards. The signed executable is selected by an
atomic link rename. The supervised launcher retries failed probationary startups;
confirmation additionally requires a healthy GUI heartbeat. Reporting/Settings
writes wait during probation to keep the previous reader's data usable.
See [offline software updates](software-updates.md) and
[data compatibility](update-data-compatibility.md).

Audio is deliberately outside the workflow's success criteria. Cue names are fixed,
asset paths cannot escape the packaged directory, native players receive argument
lists without a shell, and bounded daemon workers convert failures into sanitized
diagnostic events without blocking Tk or changing operational state.

In v1.2.0, a `StateStore.transaction()` commits each local workflow
transition and all its external delivery intents together. `DeferredIntegration`
implements semantic writes without network calls. Creation returns a stable
`local:<UUID>` reference; repair, release and later incidents do not wait for a
remote ID. Enqueue failure poisons the transaction even if a legacy best-effort
handler catches it, preventing a partial journal from being committed.

`DeliveryCoordinator` runs at most one isolated network worker. It receives an
immutable copy of the intent and frozen asset/location context, shares the live
request ledger, and never touches Tk or the live workflow state. Results enter a
one-item mailbox and are applied only between foreground operations. Creation
acknowledgements resolve pending references atomically without resetting the
current incident. Dependency ordering preserves record statuses, assignments and
asset-state sequences while unrelated operations can progress.

The journal records `sending` before dispatch. Startup requeues interrupted safe
operations and holds uncertain unsafe writes for administrator review. Stable
remote idempotency keys protect safely replayable creates; an explicit hold policy
supports native creates without claiming deduplication. Optional idempotency also
protects other operations. HTTP 429, Retry-After and transient failures produce durable
backoff rather than sleeps or busy-lock ownership. If acknowledgement persistence
fails, the result stays in memory for another local save; it is not retransmitted.
The queue is bounded to 512 operations / 2 MiB, with no automatic lifecycle expiry
or eviction. See [delivery semantics and recovery](offline-delivery.md).

Asset OFFLINE/ONLINE creation is a second independently recoverable operation. State
schema v1 persists its target, stable idempotency key, exact original request
context, and attempt count before the request. A timeout leaves these values intact,
and retry supplies the same key and byte-equivalent canonical values.
Asset and record creation each require remotely enforced idempotency or an explicit
hold-on-ambiguity policy. Asset events use the physical stop/confirmed release time,
not dispatch time. The integration layer normalizes configured response envelopes;
the controller does not interpret service-specific asset-response keys. Held asset
events support password-authorized, evidenced manual reconciliation.

Persisted state is schema-versioned and type-checked. Invalid JSON, unknown statuses/fields, malformed timers, or invalid pending work stop startup and show a state-recovery screen. The original file is preserved and a CRITICAL audit event is attempted; the application never converts corrupt state into `RUNNING` automatically.

State schema v1 persists optional failure notes, engineer selection frequency,
escalation completion, synchronization timestamps/attempts, immutable queued-event
context, pending planned work, recoverable asset-status idempotency state, and
pending response-status/participant-assignment updates. v1.2.0 adds sparse
`delivery_outbox`, `delivery_pause_until`, `roster_cache` and `roster_refresh` fields. Older pending
intents are converted by the legacy synchronization pass through the same durable
facade. Unknown fields still fail closed in older executables; a populated v1.2.0
state is not automatically downgrade-compatible. A network failure cannot reverse
the physical line decision. Directory cache entries contain only IDs and display
names, with bounded size and connection/team binding.

`services/roster.py` shares the delivery coordinator's single network worker,
bounded result queue and asynchronous state-commit path. Operational writes take
priority. `core/roster.py` defines local-calendar refresh policy and strict retry
metadata validation. Automatic refresh requires an idle kiosk; explicit refresh
is a durable request. Failed reads retain the old cache, successful reads wait for
a durable acknowledgement, and neither path rewrites connector/configuration data.
No per-person timers or worker threads are created. `ui/roster_settings.py` exposes
status and refresh, with one cancellable status timer while Settings exists.
See [saved-team semantics](team-roster.md).
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

The existing event poll checks delivery results without adding an animation timer;
dispatch scans are bounded to twice per second and still honor budgets/deadlines.
The minute synchronization pass converts legacy pending intents without network
I/O. Escalation checks every 30 seconds and fires once after `escalation_minutes`.
Starting repair clears escalation immediately. Completion classifies duration
using `micro_stop_threshold_minutes`; raw seconds and the threshold remain in the
audit event for reproducible analysis.

Accessibility uses redundant state encoding: color, status face, text, and a station glyph. `ui_color_preset=colorblind_safe` supplies a blue/amber/orange/purple palette. Locale JSON is package data in source and native builds; missing keys/locales fall back to English. Translations still require visual acceptance testing on each target display, and right-to-left mirroring is not currently claimed.

The kiosk uses content-driven geometry in `ui/layout.py`: the logical viewport
follows both available dimensions, with no fixed aspect ratio or device list.
`ui/kiosk.py` allocates status, stations, workflow and support regions; narrow
layouts stack and short layouts page. `ui/dialogs.py` shares bounded dialog
headers, measured wrapping and fixed action footers. Full Information/error/update
text remains reachable by paging. `ui/navigation.py` preserves Settings widgets
and unsaved values as its category selector changes layout. Canvas drawing and
touch hit-testing share the same scale; a resize cancels an in-flight press.

Station capacity follows the actual row width. Motion remains left-to-right on
the upper belt with an opposing return run, and stops when the line is down or
reserved. Retained scenes and bounded raster/text caches continue to protect
long-running kiosks from per-frame allocation growth. See
[adaptive kiosk layouts](adaptive-kiosk.md) for limits and verification.
