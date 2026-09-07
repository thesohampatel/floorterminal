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
| OP-1 | Any number of stations, or the whole line, can be selected before reporting | `controller/dialogs.py` selection, `ui/view.py` production map | `test_ui_smoke`, `test_integration` |
| OP-2 | Failure selection is optional and never blocks a report | `controller/dialogs.py` failure picker | `test_integration`, `test_ui_smoke` |
| OP-3 | Each station carries its own one-to-four failure list with automatic `Others` | `core/config.validate_station_failures` | `test_config`, `test_integration` |
| OP-4 | An interruption is recorded locally before any network call | `controller/workflow.report_downtime` | `test_offline_queue` |
| OP-5 | Several responders can be recorded and edited while repair is active | `controller/workflow.update_active_crew` | `test_integration`, `test_operational_enhancements` |
| OP-6 | Completion classifies duration against the micro-stop threshold | `controller/workflow.classify_downtime` | `test_operational_enhancements` |
| OP-7 | Planned Engineering work follows the same discipline with distinct text | `controller/workflow.start_planned_work` | `test_offline_queue`, `test_integration` |
| OP-8 | Support requests send messages only and create no response record | `controller/workflow.call_team` | `test_integration` |
| OP-9 | Unanswered downtime escalates once at the configured threshold | `controller/workflow.escalation_tick` | `test_operational_enhancements` |
| OP-10 | Every screen and control is reachable and fault-free in every workflow state | whole UI layer | `test_ui_smoke` (52 screens, 1,000+ controls) |

## State and data integrity

| ID | Requirement | Implementation | Verification |
|---|---|---|---|
| ST-1 | Persisted state is schema-versioned and type-checked before use | `storage/state.validate_state` | `test_state` |
| ST-2 | Corrupt or unknown state stops startup instead of assuming production is running | `storage/state.StateStore` | `test_state` |
| ST-3 | Owner-private files are written atomically through an unpredictable temporary | `core/config.write_private` | `test_security` |
| ST-4 | Audit logs are dated, retained, symlink-resistant and owner-only | `storage/audit.ActivityLogger` | `test_security`, `test_operational_enhancements` |
| ST-5 | Storage capacity is estimated against retention before it runs out | `storage/audit.storage_capacity` | `test_operational_enhancements` |
| ST-6 | Restart-restored deadlines survive a wall-clock correction | `controller/workflow.deadline_due` | `test_operational_enhancements` |
| ST-7 | An implausible system clock is reported rather than silently recorded | `core/clock.check_clock` | `test_clock` |
| ST-8 | A non-create connector failure cannot undo a local repair or Production-release transition | `controller/workflow.sync_response_status`, `sync_participant_assignment`, `try_asset_status` | `test_operational_enhancements`, `test_offline_queue` |

## Connector

| ID | Requirement | Implementation | Verification |
|---|---|---|---|
| CN-1 | There is no hardcoded provider, endpoint, key, or executable plugin | `integration/definition.py` | `test_integration`, `test_open_source_readiness` |
| CN-2 | Enabled connectors are HTTPS-only, host-restricted, and never follow redirects | `integration/runtime.py` | `test_integration` |
| CN-3 | Responses are size-bounded and remote error text is sanitised | `integration/runtime.py` | `test_integration` |
| CN-4 | Capabilities degrade independently without breaking local reporting | `services/provider.py`, `integration/workflow.py` | `test_integration`, `test_provider` |
| CN-5 | Create operations require remotely enforced idempotency | `integration/definition._validate_idempotency` | `test_integration` |
| CN-6 | Retries reuse one durable idempotency key across restarts | `controller/workflow.sync_pending_downtime` | `test_offline_queue` |
| CN-7 | The application never exceeds its rolling-minute request budget | `integration/runtime.IntegrationClient` | `test_integration` |
| CN-8 | Connector discovery is bounded and deterministic | `integration/discovery.py` | `test_connector_discovery` |
| CN-9 | Connector mappings control JSON identifier types and normalize responder names | `integration/workflow.py` | `test_integration` |
| CN-10 | Every directory lookup follows a bounded cursor and refuses repeated-cursor loops | `integration/workflow._paged_collection` | `test_integration` |
| CN-11 | Short transport retry is opt-in, bounded, and charged per attempt | `integration/definition.py`, `integration/runtime.py` | `test_integration` |

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
| SU-10 | An interruption at any point leaves a bootable terminal | `update/installer.activate` | `test_update_installer` |
| SU-11 | Configuration, connector, state and logs are never touched by an update | `update/layout.py`, `install.sh` | `test_update_installer`, `test_update_installer_script` |
| SU-12 | The availability check cannot deliver software and never blocks | `update/remote.py`, `update/service.py` | `test_update_service` |
| SU-13 | Every version change is recorded on the terminal and on the medium | `update/journal.py` | `test_update_service`, `test_update_installer` |
| SU-14 | Strict signature verification rejects small-order points and pre-validity metadata | `update/signing.py`, `update/manifest.py` | `test_update_signing`, `test_update_manifest` |

## Security and access

| ID | Requirement | Implementation | Verification |
|---|---|---|---|
| SE-1 | Settings and kiosk controls use the active installation-local PBKDF2 password; public bootstrap stops working after change | `core/settings_auth.py`, `controller/dialogs.py` | `test_settings_auth`, `test_security`, `test_ui_smoke` |
| SE-2 | Failed authentication is throttled and survives restart | `core/auth_throttle.py` | `test_security` |
| SE-3 | Private passwords/verifiers never reach a release; only the documented public bootstrap is exempt | `scripts/build/build.audit` | `test_project_profile`, release audit |
| SE-4 | Sound playback uses fixed cue names and no shell | `audio.py` | `test_audio` |
| SE-5 | No credential, endpoint or customer name is tracked in the repository | tracked templates, `.gitignore` | `test_open_source_readiness` |
| SE-6 | Private signing material cannot be committed | `.gitignore` | `test_update_deployment` |

## Accessibility

| ID | Requirement | Implementation | Verification |
|---|---|---|---|
| AX-1 | Status is carried by words, glyph, shape and motion, never colour alone | `ui/view.py` status face and station glyphs | `test_ui_smoke`, [evidence](accessibility.md) |
| AX-2 | Every control label reaches the readable minimum on its own fill | `ui/contrast.readable_label` | `test_accessibility` |
| AX-3 | Small coloured text is darkened to a readable variant of its own hue | `ui/view.readable_text` | `test_accessibility` |
| AX-4 | Status colours keep a lightness spread so they stay distinguishable | `ui/contrast.separation` | `test_accessibility` |
| AX-5 | Layout scales to any viewport without cropping the design | `ui/responsive.py` | `test_responsive` |
| AX-6 | Interface wording resolves through a locale catalogue with English fallback | `i18n/__init__.py` | `test_update_application`, `test_config` |

## Release and build

| ID | Requirement | Implementation | Verification |
|---|---|---|---|
| RE-1 | A release contains no source, bytecode, log, state or enabled connector | `scripts/build/build.audit` | `test_release_notices`, on-target verifier |
| RE-2 | Notices bind identity, licence and hashes to one build | `scripts/build/build.render_release_notices` | `test_release_notices` |
| RE-3 | An SPDX SBOM names the artifact and everything frozen into it | `scripts/build/build.write_sbom` | `test_release_notices` |
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

## Coverage

Measured with `python -m coverage` over the whole offline suite, including the
touchscreen sweep, and enforced in CI at a 70% floor:

| Area | Statements covered |
|---|---|
| Update subsystem (`update/`) | 83–94% |
| Operator view (`ui/view.py`) | 92% |
| Settings (`ui/settings.py`) | 71% |
| Controller (`app.py`, `controller/`) | 63% |
| **Whole application** | **78%** |
