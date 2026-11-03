# Requirements traceability

Each row states a requirement, where it is implemented, and the offline test that
demonstrates it. This is the map an assessor, a site quality manager, or a future
maintainer needs in order to check a claim without reading the whole tree.

Run everything referenced here with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Passing tests reduce known risk. They do not prove the absence of defects, and they
do not replace the site acceptance evidence required by
[industrial deployment](industrial-deployment.md).

## Reading the identifiers

`OP` operator workflow · `ST` state and data integrity · `CN` connector ·
`SU` software update · `SE` security and access · `AX` accessibility ·
`RE` release and build · `OPS` operations

## Operator workflow

| ID | Requirement | Implementation | Verification |
|---|---|---|---|
| OP-1 | Configured stations, or the whole line, can be selected before reporting within documented storage limits | `controller/dialogs.py` selection, `ui/kiosk.py` production map | `test_ui_smoke`, `test_integration`, `test_station_groups` |
| OP-2 | Failure selection is optional and never blocks a report | `controller/dialogs.py` failure picker | `test_integration`, `test_ui_smoke` |
| OP-3 | Each station carries its own zero-or-more custom failure list with automatic `Others`, bounded visible controls and preserved multi-select | `core/config.validate_station_failures`, `ui/failure_layout`, `ui/failure_settings` | `test_variable_failures`, `test_variable_failure_ui`, `test_quick_actions` |
| OP-4 | An interruption is recorded locally before any network call | `controller/workflow.report_downtime` | `test_offline_queue` |
| OP-5 | Several responders can be recorded and edited while repair is active | `controller/workflow.update_active_crew` | `test_integration`, `test_operational_enhancements` |
| OP-5a | Crew selection uses a bound persistent roster, with daily idle refresh, explicit Settings refresh and durable backoff without changing an open picker | `core/roster`, `services/roster`, `ui/roster_settings` | `test_daily_roster`, `test_daily_roster_ui`, `test_audit_regressions` |
| OP-6 | Completion classifies duration against the micro-stop threshold | `controller/workflow.classify_downtime` | `test_operational_enhancements` |
| OP-7 | Planned Engineering work follows the same discipline with distinct text | `controller/workflow.start_planned_work` | `test_offline_queue`, `test_integration` |
| OP-8 | Support requests send messages only and create no response record | `controller/workflow.call_team` | `test_integration` |
| OP-9 | Unanswered downtime escalates once at the configured threshold | `controller/workflow.escalation_tick` | `test_operational_enhancements` |
| OP-10 | Tested screens and registered controls remain reachable and fault-free across the workflow/viewport fixtures | whole UI layer | `test_ui_smoke` (minimum 52 rendered states and 900 control activations) |
| OP-11 | Operator self-fix and Engineering handover retain one incident, original downtime and normal release semantics | `controller/operator`, `controller/workflow` | `test_operator_response`, `operator_ui_driver` |

## Independent groups and history — 1.2.0

| ID | Requirement | Implementation | Verification |
|---|---|---|---|
| OP-12 | Groups stop independently; focus, operator handover and separate completion survive restart | `core/topology`, `controller/groups`, `storage/incidents` | `test_station_groups`, `group_ui_driver` |
| OP-13 | Group setup validates membership/impact; the touch overview remains bounded across viewports | `ui/group_settings`, `ui/group_view` | `test_station_groups`, `group_ui_driver`, `test_delivery_ui` |
| OP-14 | Routine reports use 2–3 taps and arrival/single-person crew changes/completion use 2, without removing multi-select or group semantics | `ui/operational_dialogs`, `controller/dialogs`, `controller/workflow` | `touch_budget_driver` (65 measured paths), `test_quick_actions` |
| OP-15 | Direct reporting and crew edits are durable transactions; a failed quick action can be retried without reversing its meaning; an empty crew never resumes production | `controller/dialogs`, `controller/workflow` | `test_quick_actions`, `test_completion_workflow` |
| CN-17 | Frozen per-group routing, optional structured fields and shared-asset release preserve external meaning | `integration/definition`, `integration/workflow`, `services/delivery` | `test_station_groups` |
| ST-15 | Private incident history survives crash replay, late external IDs and archive outages without silent eviction | `storage/history`, `services/history`, `storage/state` | `test_incident_history` |
| OPS-5 | Automatic history cleanup protects active/recent/pending records and rejects symlink/hard-link storage | `storage/history` | `test_incident_history` |

## State and data integrity

| ID | Requirement | Implementation | Verification |
|---|---|---|---|
| ST-1 | Persisted state is schema-versioned and type-checked before use | `storage/state.validate_state` | `test_state` |
| ST-2 | Corrupt or unknown state stops startup instead of assuming production is running | `storage/state.StateStore` | `test_state` |
| ST-3 | Owner-private files are written atomically through an unpredictable temporary | `core/config.write_private` | `test_security` |
| ST-4 | Audit logs are dated, retained, symlink-resistant and owner-only | `storage/audit.ActivityLogger` | `test_security`, `test_operational_enhancements` |
| ST-5 | Audit budget/retention adapt to disk space without deleting pending or unrelated data | `storage/housekeeping` | `test_housekeeping` |
| ST-6 | Restart-restored deadlines survive a wall-clock correction | `controller/workflow.deadline_due` | `test_operational_enhancements` |
| ST-7 | An implausible system clock is reported rather than silently recorded | `core/clock.check_clock` | `test_clock` |
| ST-8 | A non-create connector failure cannot undo a local repair or Production-release transition | `controller/workflow.sync_response_status`, `sync_participant_assignment`, `try_asset_status` | `test_operational_enhancements`, `test_offline_queue` |
| ST-9 | Local transitions and all delivery intents commit together, including before a remote ID exists | `storage/state.transaction`, `services/delivery.DeferredIntegration` | `test_delivery_journal` |
| ST-10 | Restart preserves ordering, retry pauses, uncertain-write holds and multiple incidents | `services/delivery.DeliveryCoordinator` | `test_delivery_journal` |
| ST-11 | Capacity failure cannot silently evict previously saved lifecycle work | `storage/delivery.validate_journal`, `storage/state.fail_transaction` | `test_delivery_journal` |
| ST-12 | A failed disk acknowledgement does not resend a successful network write | `services/delivery.DeliveryCoordinator.poll` | `test_delivery_journal` |
| ST-13 | A blocked external write does not take the operator busy lock or stop real Tk interaction | `services/delivery`, `app.poll_events` | `test_delivery_ui`, `delivery_ui_driver` |
| ST-14 | Audit backlog/rotation are bounded; slow log writes and unavailable health sensors do not block the UI | `storage/audit`, `services/health` | `test_housekeeping`, `test_ui_feedback` |

## Connector

| ID | Requirement | Implementation | Verification |
|---|---|---|---|
| CN-1 | There is no hardcoded provider, endpoint, key, or executable plugin | `integration/definition.py` | `test_integration`, `test_open_source_readiness` |
| CN-2 | Enabled connectors are HTTPS-only, host-restricted, and never follow redirects | `integration/runtime.py` | `test_integration` |
| CN-3 | Responses are size-bounded and remote error text is sanitised | `integration/runtime.py` | `test_integration` |
| CN-4 | Capabilities degrade independently without breaking local reporting | `services/provider.py`, `integration/workflow.py` | `test_integration`, `test_provider` |
| CN-5 | Create operations require real deduplication or explicit hold-on-ambiguity; all optional guarantees are validated | `integration/definition`, `services/delivery` | `test_integration`, `test_connector_compatibility`, `test_delivery_journal` |
| CN-6 | Connectors declaring real create deduplication reuse a durable key across retries/restarts; uncertain non-idempotent writes are held | `storage/delivery`, `services/delivery`, `controller/workflow.sync_pending_downtime` | `test_delivery_journal`, `test_connector_compatibility`, `test_offline_queue` |
| CN-7 | The application never exceeds its rolling-minute request budget | `integration/runtime.IntegrationClient` | `test_integration` |
| CN-8 | Connector discovery is bounded and deterministic | `integration/discovery.py` | `test_connector_discovery` |
| CN-9 | Connector mappings control JSON identifier types and normalize responder names | `integration/workflow.py` | `test_integration` |
| CN-10 | Every directory lookup follows a bounded cursor and refuses repeated-cursor loops | `integration/workflow._paged_collection` | `test_integration` |
| CN-11 | Short transport retry is opt-in, bounded, and charged per attempt | `integration/definition.py`, `integration/runtime.py` | `test_integration` |
| CN-12 | Service cooldowns, HTTP-date Retry-After and the app budget share a single request ledger | `core/rate_policy`, `integration/runtime` | `test_delivery_journal`, `test_integration` |
| CN-13 | Queued operations cannot silently move to a different connector or asset | `storage/delivery.binding`, `services/delivery` | `test_delivery_journal` |
| CN-14 | Partial directories and same-name group/person collisions cannot silently choose a recipient | `integration/directory`, `integration/workflow` | `test_connector_compatibility`, `test_audit_regressions` |
| CN-15 | Asset history retains original stop/release times and supports protected, evidenced reconciliation | `controller/workflow`, `services/delivery`, `controller/dialogs` | `test_delivery_journal`, `delivery_ui_driver` |
| CN-16 | Configured nested request/response fields remain data-only and typed | `integration/mapping`, `integration/schema`, `integration/workflow` | `test_connector_compatibility` |

## Software update

| ID | Requirement | Implementation | Verification |
|---|---|---|---|
| SU-1 | Update metadata must carry a maintainer signature made by a build-time key | `update/manifest.py`, `update/trust.py` | `test_update_manifest`, `test_update_signing` |
| SU-2 | The signature algorithm matches the RFC 8032 reference implementation | `update/signing.py` | `test_update_signing` (RFC 8032 §7.1 vectors) |
| SU-3 | Nothing on removable media is executed, sourced, or followed through a symlink | `update/media.py` | `test_update_media` |
| SU-4 | The payload is verified on the medium, while copying, and again from disk | `update/media.stage` | `test_update_media` |
| SU-5 | The update source cannot be changed by configuration or environment | `update/trust.py` | `test_update_deployment` |
| SU-6 | Installation requires attributed administrator authorization | `controller/updates.py` | `test_update_application` |
| SU-7 | Activating a version replaces one symbolic link atomically | `update/installer._swap_link` | `test_update_installer` |
| SU-8 | The previously accepted version stays installed and launchable | `update/installer.prune` | `test_update_installer` |
| SU-9 | A version that cannot start is restored without operator action | `packaging/linux/floorterminal-launch` | `test_update_launcher` (run as a real process) |
| SU-10 | Tested activation interruptions retain a complete executable slot and recoverable activation intent | `update/installer.activate` | `test_update_installer` |
| SU-11 | Runtime data is preserved; compatibility is checked before switching and old operational state is not replayed | `update/compatibility.py`, `install.sh` | `test_update_compatibility`, `test_update_installer_script` |
| SU-12 | The availability check cannot deliver software and never blocks | `update/remote.py`, `update/service.py` | `test_update_service` |
| SU-13 | Every version change is recorded on the terminal and on the medium | `update/journal.py` | `test_update_service`, `test_update_installer` |
| SU-14 | Strict signature verification rejects small-order points and pre-validity metadata | `update/signing.py`, `update/manifest.py` | `test_update_signing`, `test_update_manifest` |
| SU-15 | Private bounded checkpoints and missing-extension recovery preserve connector bytes and newer edits | `update/compatibility`, `core/config` | `test_update_compatibility` |
| SU-16 | Save precedes activation; queued/in-flight work and incompatible targets block a version change | `controller/updates`, `update/installer` | `test_update_compatibility`, `test_update_application` |
| SU-17 | Confirmation needs a healthy GUI heartbeat; invalid supervised startup requests recovery | `update/service`, `update/compatibility`, `app` | `test_update_service`, `test_update_compatibility` |

## Security and access

| ID | Requirement | Implementation | Verification |
|---|---|---|---|
| SE-1 | Settings and kiosk controls use the active installation-local PBKDF2 password; public bootstrap stops working after change | `core/settings_auth.py`, `controller/dialogs.py` | `test_settings_auth`, `test_security`, `test_ui_smoke` |
| SE-2 | Failed authentication is throttled and survives restart | `core/auth_throttle.py` | `test_security` |
| SE-3 | Private passwords/verifiers never reach a release; only the documented public bootstrap is exempt | `scripts/build/build.audit` | `test_project_profile`, release audit |
| SE-4 | Sound playback uses fixed cue names and no shell | `audio.py` | `test_audio` |
| SE-5 | Public templates contain no live integration credentials, customer endpoints or deployment identity | tracked templates, `.gitignore` | `test_open_source_readiness`, secret scanning |
| SE-6 | Private signing files are excluded from ordinary staging and rejected by publication checks; never bypass these safeguards with forced staging | `.gitignore`, `scripts/release/verify_publication.py` | `test_update_deployment`, `test_publication_gate`, secret scanning |
| SE-7 | Authentication and audit paths reject unsafe file types/links; malformed security state fails conservatively without stopping operator reporting | `core/auth_throttle`, `core/settings_auth`, `storage/audit`, `storage/housekeeping` | `test_kiosk_hardening`, `test_settings_auth`, `test_security` |

## Accessibility

| ID | Requirement | Implementation | Verification |
|---|---|---|---|
| AX-1 | Status is carried by words, glyph, shape and motion, never colour alone | `ui/view.py` status face and station glyphs | `test_ui_smoke`, [evidence](accessibility.md) |
| AX-2 | Every control label reaches the readable minimum on its own fill | `ui/contrast.readable_label` | `test_accessibility` |
| AX-3 | Small coloured text is darkened to a readable variant of its own hue | `ui/view.readable_text` | `test_accessibility` |
| AX-4 | Status colours keep a lightness spread so they stay distinguishable | `ui/contrast.separation` | `test_accessibility` |
| AX-5 | Layout reflows at supported viewports and keeps tested touch targets in bounds; the minimum usable viewport is documented | `ui/responsive.py`, `ui/layout.py`, `ui/kiosk.py` | `test_responsive`, `test_adaptive_layout`, `test_quick_actions` |
| AX-6 | Interface wording resolves through a locale catalogue with English fallback | `i18n/__init__.py` | `test_update_application`, `test_config` |

## Release and build

| ID | Requirement | Implementation | Verification |
|---|---|---|---|
| RE-1 | A runtime bundle contains no loose source/bytecode files, logs, live state or enabled connector; the executable includes its frozen Python runtime | `scripts/build/build.audit` | `test_release_notices`, on-target verifier |
| RE-2 | Notices bind identity, licence and hashes to one build | `scripts/build/build.render_release_notices` | `test_release_notices` |
| RE-3 | An SPDX SBOM records the application hash and declared Python, toolkit and build-tool components; it is not a file-level inventory of every bundled library | `scripts/build/build.write_sbom` | `test_release_notices` |
| RE-4 | Every build attempt leaves an immutable owner-side record | `scripts/build/build.BuildRecorder` | `test_build_history` |
| RE-5 | The delivered file set is exact and verified on the target | `scripts/install/prepare_release_on_pi.sh` | `test_linux_packaging`, `test_update_deployment` |
| RE-6 | The installer creates a managed layout and preserves deployment data | `packaging/linux/install.sh` | `test_update_installer_script` (runs the real script) |

## Operations

| ID | Requirement | Implementation | Verification |
|---|---|---|---|
| OPS-1 | The kiosk restarts after a crash or unauthorized closure | `floorterminal.service`, `floorterminal-launch` | `test_linux_packaging`, `test_update_launcher` |
| OPS-2 | The service runs under a hardened sandbox with no capabilities | `floorterminal.service` | `test_linux_packaging`, `test_update_deployment` |
| OPS-3 | Configuration is validated before it is accepted, in file and in Settings | `core/config.validate_config` | `test_config` |
| OPS-4 | Entry points start the application from source and as a module | `main.py`, `__main__.py` | `test_entrypoints` |
| OPS-6 | Opaque dialogs avoid hidden rendering while input wakes a single animation timer; failed health checks recover | `ui/kiosk`, `ui/view`, `app` | `test_kiosk_hardening`, `test_ui_feedback`, `render_stress_driver --dialog about` |
| OPS-7 | Audio concurrency is bounded, and failed HTTP responses explicitly release resources | `audio`, `integration/runtime`, `update/remote` | `test_kiosk_hardening`, `test_audio` |

## Coverage

Measured on **3 November 2026** with `python -m coverage` over the 727-test
offline Pi suite, including graphical subprocesses, and enforced in CI at a 70%
whole-application floor. Subsystem totals below are weighted by statement count;
they are not averages of individual files:

| Area | Statements covered |
|---|---|
| Update subsystem (`update/`) | 90.5% |
| Shared operator-view helpers (`ui/view.py`) | 94% |
| Settings (`ui/settings.py`) | 85% |
| Controller (`app.py`, `controller/`) | 82.2% |
| **Whole application** | **88%** |

The adaptive production map also lives in `ui/kiosk.py` and `ui/group_view.py`;
the `ui/view.py` figure alone does not describe all GUI coverage. See
[verification](verification.md) for native measurements and acceptance limits.
