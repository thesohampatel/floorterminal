# Release verification

## v1.2.1 release verification — 4 November 2026

The native ARM64 release was built on Raspberry Pi 5 / 64-bit Raspberry Pi OS
(Debian 13, glibc 2.41), Python 3.13.5 / Tk 8.6, with PyInstaller 6.21.0.

- **755 offline tests pass with zero skips** on the real Pi graphical session
  before compilation. The macOS source run passes with 28 graphical skips, covered
  by the Pi run. Ruff 0.17.3 and the source-matched artifact audit pass.
- The delivered **14-file installation bundle** contains no source, logs, saved
  incidents, enabled connector or live credentials. The four public downloads
  comprise installation/update archives and their two SHA-256 sidecars. Package
  and channel signatures verify against the pinned public key; signing is local
  and the private key never enters the Pi, repository or release assets.
- The **compiled executable** passes native 1920×1200 fullscreen animation,
  Information, protected Settings, return-to-main and the finalized Version panel.
  Actual X input completes two standalone incident cycles. An abrupt process
  restart retains the original self-fix incident and start time; Engineering
  handover continues that incident. No application/callback/save errors occur.
- An actual **v1.2.0 → v1.2.1 → v1.2.0 → v1.2.1** executable round trip passes
  authenticated activation, compatibility probes and rollback in disposable
  managed storage. Both connector files remain byte-identical. The published
  v1.2.0 Settings writer preserves unknown configuration fields, including the
  new support shortcuts, while a changed line name survives the return upgrade.
  This is not a claim that arbitrary manual deletion of configuration is repaired.
- The [native gallery manifest](images/v1.2.1/manifest.json) binds **135 media
  assets** to the finalized source input digest, including keyboard, failure-card,
  support-button, Information and Update checks at compact, portrait and large
  sizes. Update-availability examples use explicitly illustrative service
  snapshots; they do not announce any hypothetical next version.
- No real third-party API/account or production installation is used. The
  existing kiosk executable, service/autostart and runtime data stay untouched.
  Physical power loss, gloves/fingers, site connector commissioning and multi-month
  endurance remain deployment acceptance work; passing tests are not a guarantee
  of zero defects or vulnerabilities.

Build ID: `bf992748-75f9-4db4-a6d6-ee2f26bba990`.
Source-input SHA-256:
`1c77b8d96008591181be031b7936a9de753f5cbf91322afcecbec6dd0340b4f6`.
Executable SHA-256:
`16dacdc09dcafb69918f2b298473b633950adbb58c8ad5431e48204d7f49fddd`.

## v1.2.1 pre-release interface measurements — 4 November 2026

The following short measurements were collected before release metadata was
finalized. They cover the same interface implementation, not a long-running
production installation. Earlier-version evidence below remains historical.

- **755 offline tests pass with zero skips** on the ARM64 touchscreen kiosk Pi,
  using its real Tk graphical session and disposable runtime data. This includes
  adaptive screen geometry, incident/group workflows, Settings saves, update
  compatibility and the new touch-refinement regressions.
- The macOS development run also passes **755 tests, with 28 graphical skips**
  in its non-graphical test environment. Those skips are covered by the native Pi
  run; they are not presented as successful macOS graphical tests.
- A dedicated real-Tk driver checks 320×400, 800×480, 480×800 and 1920×1200:
  reserved clock bounds, all 68 uppercase/digit/punctuation keys, case/delete,
  equal-size failure grids, optional multi-selection, Information tabs and Update
  layout. It saves custom support settings through the real Settings writer and
  verifies enabled/disabled controls and dispatch. Network connections are denied.
- The compact default five-choice failure sheet remains on one screen and the
  existing short reporting/arrival/completion/crew paths pass. Arbitrary larger
  catalogues still use bounded paging/search without losing selections.
- Ruff **0.17.3** and the offline source/publication audit pass. Gitleaks finds
  no secrets in the development source snapshot. The signed channel remains at
  v1.2.0; release gates still reject development wording in an announced build.
- A short native **1920×1200 fullscreen** sample draws 301 frames in ten seconds,
  with **3.34 ms p95 render-call time**, a **23.84 ms maximum nominal 20-ms
  heartbeat gap** and 10.6% process CPU. A static dialog draws only two frames
  in two seconds. These are event-loop measurements, not physical touch latency.
- Settings gives initial feedback after **77 ms** and finishes first construction
  after **886 ms**, with a 153 ms maximum construction-time event gap. A loading
  cover hides partially constructed forms; first-open latency is still measurable.
- Grouped scenes render **1,000 measured frames** at each of 800×480 and
  1920×1200. No canvas items are recreated after warm-up; RSS growth is 16 KiB in
  each run, with raster caches around 9.3 and 13.5 MiB. This bounded-resource
  sample is not a multi-month endurance or memory-leak guarantee.
- No external service/API, private signing key, production runtime file, installed
  kiosk executable or system service is changed by these checks. Passing tests
  are not a guarantee of defect-free software or a substitute for site acceptance.

## 1.2.0 — corrected distribution verification

The owner approved a same-version reissue on **3 November 2026** to correct stale
compiled release text and refresh the documentation gallery. See the
[reissue notice and executable identifiers](releases/v1.2.0-reissue.md) before
reinstalling an existing 1.2.0 terminal. The version stays 1.2.0; this is not a
normal version-increasing USB update.

- **734 offline tests pass with zero skips** on the physical Pi 5 graphical
  session (64-bit Raspberry Pi OS, Python 3.13.5 / Tk 8.6). Five new release-catalogue
  checks reject preview wording, invalid dates, mismatched release notes and invalid
  capability lists. Two new installer regressions exercise same-version replacement:
  configuration, multiple connectors, password, state, history and journal bytes
  survive; corrupt replacement checksums leave the executable unchanged.
- The installer regressions run the real installer with unprivileged command
  shims in disposable directories. They do not modify the site's `/opt` installation
  or establish that every deployment-specific launcher will stop correctly.
- The rebuilt ARM64 bundle contains exactly **14 runtime files** and passes the
  source-input, neutral-template and content audits. Build ID:
  `407f8f66-ca48-4976-913f-9ba610e9162f`. The source-input digest is
  `62f4d99f4439b65f1ecb2be685d30f5abc940aa2d20216fd64a036bdaefef5b1`.
- The signing key stays on the maintainer's workstation outside the repository.
  The install archive, signed USB archive, both checksum sidecars and signed channel
  are checked together against the pinned public key and reviewed source inputs.
- The **rebuilt executable** passes native 1920×1200 fullscreen animation,
  Information, protected Settings and the corrected Version panel. Actual input
  completes two standalone incident cycles. An abrupt process restart restores the
  same self-fix incident and start time; Engineering handover keeps that identity.
  No callback, rendering, saving or application errors are recorded.
- Authenticated activation and rollback/return pass with this real compiled
  candidate. Connector bytes remain unchanged and newer edits survive restoration.
  The old slot is a controlled fixture, not a complete historical release binary;
  this is not a physical power-loss or all-version compatibility certification.
- The gallery is regenerated from the corrected source, including its Version
  panel. The [manifest](images/v1.2.0/manifest.json) binds all **102 assets** to that
  source digest. Capture drivers check groups, self-fix, touch paths, flexible
  failure reasons, saved teams, delivery, Settings and adaptive layouts. Animation
  clips illustrate the real renderer with fixed time steps, not a measured fps claim.
- The macOS development desktop constrains oversized test windows to its available
  1440×777 workspace. Two geometry tests failed there because their requested large
  or tall windows were clamped; the complete geometry suite passed on the Pi.
  Those desktop results are not counted as a successful full macOS GUI run.
- No real integration API is called. The installed kiosk, its configuration and
  its service/autostart are not replaced. Site acceptance and long-duration limits
  described below remain applicable; passing tests are not a defect-free guarantee.

## Original v1.2.0 distribution — historical evidence

**Published 3 November 2026:** [v1.2.0 downloads](https://github.com/thesohampatel/floorterminal/releases/tag/v1.2.0)
and [merged release PR #16](https://github.com/thesohampatel/floorterminal/pull/16).
The original release tag initially pointed to `a077a34aadf6107800be952061be1fce3c69386c`;
that source tree was identical to the reviewed candidate. The four original public downloads
and both signed update-channel files were fetched without authentication and
SHA-256 compared against the audited originals. Required PR checks and the
post-merge Python 3.11–3.14 CI, secret scan and CodeQL analysis passed.

The original checks below did not detect the stale compiled Version description.
The new catalogue gate above closes that gap. The current [gallery](images/README.md)
and downloads reflect the corrected distribution; these earlier results are
historical evidence, not identifiers for the current artifacts.

### Final source and native build — 3 November 2026

- **727 offline tests pass with zero skips** on the physical Pi 5 graphical
  session, using Python 3.13.5 / Tk 8.6. A separate subprocess-aware coverage run
  also passes all 727 tests and measures **88% statement coverage** of the
  application (11,026 statements). The macOS Python 3.14.7 run passes with 27
  graphical skips, covered by the Pi run. Ruff 0.16.10 passes.
- The four final regression tests protect documentation captures: example update
  versions follow the package version, the offline update fixture accepts GUI
  heartbeats, and failed rendering cannot silently become a published screenshot.
  All **22 primary walkthrough images/animations** were regenerated from native
  1600×960 Pi rendering. Update examples are explicitly illustrative; they do not
  announce a future release.
- A separate two-minute **1920×1200 fullscreen** source-GUI sample records 3,626
  frames (about 30 frames/second), **2.97 ms p95 render-call time**, and a **24.0 ms
  maximum nominal 20-ms heartbeat gap**. Process CPU averages 9.86% in this sample.
  The static dialog draws two frames in two seconds and averages 0.64% CPU.
  All six Settings footers pass hit-target checks, with no callback failures.
- Settings shows feedback after approximately **115 ms** and completes its first
  construction after **1.46 s**. Its largest construction-time event gap is
  **468 ms**. The loading cover prevents partially built forms from being exposed;
  this measured first-open pause remains a limitation, not a zero-latency claim.
- The final **Linux ARM64 executable** is built on Pi OS / Debian 13 with
  glibc 2.41 and PyInstaller 6.21.0. Its **14-file runtime audit passes**: disabled
  neutral connector, no source, runtime state, logs or live credentials. Its source
  input manifest matches the reviewed source byte-for-byte. Older Linux systems
  may need a native rebuild rather than this binary.
- The compiled executable passes native fullscreen main-screen animation,
  Information, password-protected Settings, return-to-main and Software Update
  checks. The captures were visually inspected; the driver reports no callback
  errors. Authenticated activation and rollback/return also pass using the real
  compiled candidate and headless compatibility probes. The old slot is an
  explicitly controlled fixture, **not an actual older-release binary**. Connector
  bytes stay unchanged and newer configuration edits survive restoration.
- The installation archive, signed USB archive, both SHA-256 sidecars and signed
  channel are verified together against the pinned public key and source-input
  manifest. The private signing key stays outside the repository and artifacts.
  Tests use disposable neutral data and make **no live integration calls**; the
  installed kiosk and its service/autostart are not replaced by this verification.

These results describe the candidate subsequently published as v1.2.0.
Download its verified assets from GitHub Releases. Site commissioning,
physical finger/glove interaction, full historical-binary round trips, physical
power-loss testing and multi-month endurance remain deployment acceptance work.
Passing tests and secret scanning do not certify the absence of every defect or
vulnerability. See [v1.2.0 release notes](releases/v1.2.0.md) for the feature summary
and [update data compatibility](update-data-compatibility.md) for safe refusal rules.

### Independent final kiosk recheck — 3 November 2026

A fresh isolated copy of the candidate was tested again on the physical Pi 5,
without installing over the existing kiosk or enabling external services:

- The complete **727-test suite passes again with no skips**. Native group touch,
  blocked-delivery, daily-roster, compiled-update and compiled-GUI checks also pass
  individually. The group driver checks 18 views and two independent incidents.
- A **five-minute 1920×1200 fullscreen** sample records 9,036 frames (30.12 fps),
  3.48 ms p95 render-call time, a 24.47 ms maximum nominal 20-ms heartbeat gap and
  11.54% process CPU. The static dialog draws only two frames in two seconds.
- A grouped scene runs **10,000 measured frames at each of 800×480 and 1920×1200**,
  after warm-up. No canvas items are recreated during either measured run. RSS
  growth is 304 KiB and 16 KiB respectively; raster caches use approximately
  9.1 MiB and 13.4 MiB. This short bounded-resource sample is not a long-duration
  memory-leak or endurance guarantee.
- Settings shows initial feedback at 71 ms and finishes construction at 743 ms in
  this run, with a 134 ms maximum construction-time event gap. The earlier 1.46 s
  result above remains relevant: first-open latency varies with system conditions.
- A deliberately blocked in-memory delivery has a 37.4 ms maximum heartbeat gap;
  four deliberately slow local writes keep it below 26.68 ms. No duplicate record
  is produced. Thirty cached crew-picker opens require only the fixture's two
  initial directory requests; names, current selections and configuration remain
  stable. These are fixture requests, **not real API traffic**.
- Actual input into the **compiled executable** completes two standalone incident
  cycles. An abrupt process kill/restart during operator self-fix restores the
  same incident and original start time; Engineering handover then retains that
  identity before production resumes. An ordinary Engineering response also
  completes. Saved history drains, no remote writes are queued in local mode,
  and the driver reports no application/callback/save errors. This exercises
  process interruption, not a physical power cut or damaged storage medium.
- The compiled workflow driver was corrected to allow a fresh idle deployment
  without a state file, and to wait for history acknowledgement before its next
  action. A tap during the brief local-saving guard is explicitly rejected with
  feedback, not queued. This remains documented behavior; the recheck does not
  claim every tap is accepted during concurrent local persistence.
- Neutral compact/portrait group screenshots were visually inspected. Final
  signatures, source matching, shell syntax and Git-history secret checks pass.
  No new runtime defect was reproduced. Documentation corrections remove obsolete
  fixed-grid/physical-touch-size claims, refresh coverage figures and clarify
  localization, inventory and staging safeguards. Compiled inputs remain unchanged.

<details>
<summary>Historical v1.2.0 development checks — not the current release status</summary>

### Earlier development evidence

The dated entries below record checks at their respective development snapshots;
their counts and then-current release/channel status are historical, not the final
candidate's status.

### Persistent daily team roster — 2 November 2026

- **723 offline tests pass with zero skips** on the physical Pi 5 graphical
  session (ARM64, Python 3.13.5 / Tk 8.6). The macOS run passes with 27 graphical
  skips covered on the Pi. Twenty-two added tests cover the persistent refresh
  policy and its native Settings/crew-screen behavior.
- Regression coverage includes repeated picker opens without network or state
  writes, cache reuse after restart, midnight and daylight-saving boundaries,
  idle deferral across groups, manual request coalescing, partial/empty/invalid
  directories, connector/team changes, interrupted refreshes and failed saves.
  A service cooldown **longer than one day** is retained across restart; repeated
  taps cannot bypass it. Operational deliveries keep priority over roster reads.
- The native GUI driver passes at **800×480, 480×800 and 1920×1200**. Refresh and
  Save/Cancel remain visible and touchable. While the fixture directory request
  is deliberately blocked, 30 cached picker opens remain usable. The run makes
  exactly two in-memory requests (team lookup and members), records a **27.38 ms**
  maximum nominal 20-ms heartbeat gap, and reports no callback errors or live
  connections. An open picker stays stable when refreshed names arrive.
- Configuration and connector files remain byte-identical; roster names and retry
  metadata belong to private runtime state. Neutral native landscape/portrait
  previews were captured and visually reviewed. No real account, credential or
  provider API was used. Ruff, whitespace, offline source/publication checks and
  secret scanning pass.
- Version remains **1.2.0 unreleased**. This change does not build, sign, publish,
  replace the installed kiosk or alter its service/autostart. The isolated remote
  source and capture directories are removed after verification.

See [saved team members](team-roster.md) for behavior, privacy, bounds and setup.
These checks are not live-directory commissioning, physical finger/glove tests
or long-duration endurance certification.

### Variable failure catalogues and group connectors — 2 November 2026

- **701 offline tests pass with zero skips** on the physical Pi 5 graphical
  session (ARM64, Python 3.13.5 / Tk 8.6). The macOS run passes the same suite
  with 26 graphical skips covered on the Pi. Version remains 1.2.0 unreleased;
  no signed channel, installed kiosk, service or autostart is changed.
- Sixteen added regressions cover Others-only and 10,000-reason configuration,
  validation, complete catalogue paging, search/selection preservation, editor
  add/remove, real state-file restart, multiple reported stations and group
  propagation, keyed team/person assignments, structured remote metadata and
  lossless refusal of unsupported downgrades. An existing workflow harness now
  deep-copies configuration defaults so tests cannot alter subsequent fixtures;
  the focused suites also pass in both execution orders.
- The native GUI driver checks **30 catalogue/viewport combinations**: 0, 1, 4,
  8, 53 and 1,000 custom reasons at 320×400, 800×480, 480×800, 1280×800 and
  1920×1200. It checks in-bounds nonoverlapping touch targets, persistent
  selections, automatic Others, All/None, navigation and search. A 101-reason
  Settings draft retains off-page edits across station changes; active incidents
  refuse catalogue changes without modifying the configuration file.
- Native 800×480 and 480×800 previews were captured and visually reviewed, using
  neutral disposable data. Only visible reason cards are drawn; the editor reuses
  four rows. Large selected-reason arrays are frozen in record creation, not
  unnecessarily repeated in every later status/chat intent.
- Public API documentation informed neutral wire-contract fixtures. Tests assert
  exact assignment/metadata payloads, independent asset routing, shared-asset
  last-release behavior and the absence of an arbitrary scalar asset for multiple
  assets. No live provider, key or socket connection is used. Optional mappings
  do not establish that every external account/schema accepts those fields.
- Ruff, whitespace, the offline source/publication audit and secret scanning pass.
  The isolated Pi source/capture workspace is disposable; no new release or
  compiled binary is produced for this development change.

See [failure reasons](failure-reasons.md), [station groups](station-groups.md) and
[connector commissioning](connector-commissioning.md). These checks do not replace
site-specific integration, finger/glove usability, external payload-limit testing
or long-duration endurance acceptance, and do not certify the absence of all bugs.

### USB update data safety and Pi acceptance — 1 November 2026

- **685 offline tests pass with zero skips** on the physical Pi 5 graphical
  session (ARM64, Python 3.13.5). The macOS headless run also passes, with 25
  graphical skips covered on the Pi. The suite includes real launcher/installer
  subprocesses, interrupted activation, retained versions, private checkpoints,
  unsupported schema/feature refusals, failed saves, concurrent-file detection,
  probe timeout/output limits, missing connectors and GUI-health confirmation.
- First-upgrade regressions ensure an older updater cannot start legacy-incident
  migration while responses or deliveries are unfinished: supervised startup
  requests recovery without modifying those runtime bytes. A healthy idle startup
  remains read-only. Lost configuration extensions merge back only when absent;
  later settings edits and rotated connector credentials are preserved.
- The final source builds with the pinned PyInstaller 6.21.0 on the Pi. Its
  **14-file bundle audit passes**, including the disabled neutral connector and
  exclusion of source, live state and logs. The build input manifest matches the
  reviewed clean staging source. No production signing key or release is used.
- The compiled ARM64 executable passes `update_binary_driver.py`: real headless
  candidate probes, authenticated activation using a throwaway in-memory test key,
  rollback/return, two byte-identical connector files and missing-extension
  restoration that preserves newer edits. The older slot is explicitly a fixture,
  **not** an acceptance test of an older compiled release or arbitrary future API.
- A separate **1920×1200 fullscreen** source-GUI check passes all six Settings
  footers and captures the main, Information, password, crew, failure and Settings
  screens. Main/station-editor captures were visually inspected. The short sample
  records 302 frames in ten seconds, 2.94 ms p95 render-call time and a 22.57 ms
  maximum event-loop heartbeat gap; there are no callback errors or service calls.
  Static dialogs render two frames in two seconds. Settings shows feedback at
  107 ms and completes at 1.35 s, with a 478 ms maximum construction-time event gap:
  first-open construction is still a measured limitation, not a zero-lag claim.
- Physical testing reproduced off-screen station actions at 800×480. Station
  selection/actions are now pinned while detail fields scroll independently;
  the focused GUI regressions and full Pi suite pass after the correction.
- Ruff, whitespace, offline source audit and secret scanning pass. The private
  test workspace/build tools are disposable; no installed kiosk, service,
  autostart, real connector, signing key, public channel or release is changed.
  Version remains **1.2.0 unreleased**, with the signed channel still on 1.1.0.

See [update data compatibility](update-data-compatibility.md) for supported
behavior and refusal rules. Physical power cuts, full historical-binary round
trips, external-service commissioning, finger/glove usability and long endurance
remain site/release acceptance work; these results do not certify universal
forward/backward compatibility or the absence of every bug or vulnerability.

### Connector contracts and physical-kiosk recovery — 31 October 2026

- The physical Pi 5 graphical session passes **653 offline tests with zero skips**
  on ARM64 / Python 3.13.5. This includes actual Tk rendering, generated touch
  input, adaptive layouts, operator self-fix, independent groups, crew edits,
  completion/restart recovery and the protected asset-event review screen.
- Thirty-four additional regressions cover external-reference upsert keys, native
  creation with explicit held-write recovery, original stop/release timestamps,
  nested mappings, scalar types, partial/repeated-cursor directories, recipient
  collisions, group-only/person-only messaging, malformed definitions, strict
  responses, literal/encoded credential redaction and read-only diagnostics. The one-request-per-minute retry/roster
  tests remain passing; no lookup is mistaken for a complete partial directory.
- A separate native **1920×1200 fullscreen** check records 907 frames in 30 seconds,
  2.95 ms p95 render-call time and a 23.09 ms maximum heartbeat gap, with zero
  callback faults and zero live connections. The static dialog renders two frames
  in two seconds. The blocked-write driver measures a 28.92 ms maximum heartbeat
  gap; four deliberately slow storage writes keep it below 32.40 ms. Neutral
  main-screen, Settings and 800×480/480×800 reconciliation captures were visually
  inspected. These short tests are not a multi-month soak guarantee.
- Settings shows its loading cover at 101 ms and completes at 1.46 seconds; its
  maximum construction-time event gap remains 527 ms. This existing first-open
  limitation is recorded, not described as zero-latency rendering. All six pages
  and the Save/Cancel hit targets pass the physical-panel checks.
- The source audit, Ruff and whitespace checks pass. Secret scanning finds no
  secrets in the reviewed Git history. Twenty-six whole-directory scanner findings
  were verified as SHA-256 source-file checksums in ignored build manifests, not
  credentials. No provider-specific artifact, real credential or service call is
  included in the tests or committed fixtures.
- Native macOS/Tk 9.0.3 was also tried: the focused recovery-screen driver passes,
  but the broader artificial-resolution sweep encounters window-manager size
  clamps and a station-editor visibility assertion. That attempt is **not** a
  full macOS GUI pass; oversized-window simulation and the Tk 9 station-editor
  assertion remain platform follow-up checks. The accepted kiosk evidence is the
  real Pi graphical run, not a claim that every desktop environment is certified.
- All external operations use in-memory transports with sockets blocked. Public
  documentation/schema comparison informs the neutral contract fixtures but is
  not a live-service compatibility certification. Deployment owners must complete
  [connector commissioning](connector-commissioning.md) using an authorized
  non-production account. Status changes do not imply native labor-timer control.
- Version remains **1.2.0 unreleased**; the signed public channel remains 1.1.0.
  No release, signing-key change, installed-kiosk replacement or autostart change
  is part of this audit.

### Rendering and kiosk controls — 29 October 2026

- **619 offline tests pass, zero skips** on the attached Pi 5 graphical session,
  including the final stationary-controls/reflow changes. The macOS run passes
  with 25 graphical skips. The independent second Pi also passes the suite with
  25 display-dependent skips. No provider API or real connector key is used.
- Seventeen additional regressions cover stable animation primitives through blink
  and wrap cycles, belt geometry and stop/resume, bounded images, opaque identity
  composition, deferred Settings cancellation/failure, field selection/grab
  restoration, editable names, repeated picker cleanup and keyboard-triggered transitions. The existing
  4,632-case adaptive sweep, 65 routine touch paths, durable group reporting,
  restart recovery and blocked-I/O tests remain in the passing suite.
- An uninterrupted **120-second actual mainloop** sample records 3,628 frames,
  2.95 ms p95 render-call time and a 30.09 ms maximum 20-ms heartbeat interval.
  There are no callback errors. Settings feedback appears at 106 ms and the
  complete form at 1.42 s; its initial construction still has a measured 502-ms
  maximum event gap. This is a documented limitation, not a zero-latency claim.
- A further 6,000 grouped frames across 800×480, 480×800 and 1920×1200 show
  **zero recreated canvas items after warm-up**, 1.303–3.441 ms p95 render time
  and 0–64 KiB RSS growth. These synthetic long-phase runs do not constitute
  months of endurance testing. [Method and measured limits](ui-performance.md#animation-and-panel-redraw-fixes--29-october-2026).
- Native main, group, crew and Settings screenshots are inspected. All six
  Settings footers pass actual pointer-hit testing. Touch option sheets remain
  inside the app at small, portrait and large sizes; Back preserves values and
  restores input ownership. Updated neutral documentation previews are included.
- Ruff, whitespace and the offline repository audit pass. No dependency, version,
  connector contract, update channel, signing material, installed production
  service or production runtime data is changed. This remains **1.2.0 development**;
  no release or remote push is performed. A separate disposable, offline preview
  can be used for physical review without replacing the installed application.

Hands-on glove/touch testing, representative multi-day endurance, and compiled
release acceptance remain commissioning work. Automated GUI tests and a short
measured run do not certify an absence of all freezes, bugs or security issues.

#### Overnight follow-up — 30 October 2026

The same isolated offline preview was still running after **17 hours**, with no
errors in its preview log. Six native-screen samples of the conveyor region
changed in all five successive intervals, confirming visible motion at the time
of inspection. The process RSS snapshot was approximately 80 MiB; the Pi reported
47.2°C and no throttling flags. This is a follow-up observation, not continuous
frame-time instrumentation, a memory-growth measurement or a connected-production
load test. No provider traffic or production data was involved. Temporary
diagnostic captures/logs were removed; the offline preview remained open for
hands-on inspection without replacing the installed application.

### Completion checks — 28 October 2026

The final fullscreen panel driver passes on the same attached 1920×1200 Pi
display, including **Save/Cancel pointer-hit testing** so an in-bounds button
cannot pass merely because it is mapped underneath another widget. All six
Settings pages pass; no callback faults or external connections occur.

The ten-second main-screen sample records 290 frames, 2.15 ms p95 render-call time
and a 27.00 ms maximum heartbeat interval. The static password-page sample still
renders only two frames in two seconds. The Pi reports 40.6°C before this run;
the earlier thermal observations below remain part of the dated evidence, not a
claim about its current cooling condition. The desktop/service configuration is
unchanged and the isolated remote test folder is removed after validation.

The final repository copy passes the 602-test macOS run with the expected 16
graphical skips; the complete 602-test Pi pass is recorded below. Ruff, whitespace
and the offline repository audit pass. Secret scanning finds no secrets in the
reviewed public source or available Git history. Whole-folder scanner hits in
ignored build manifests were checked and are source-file SHA-256 checksums, not
credentials. No release is built, signed, installed, pushed or published here.

### Physical-panel check — 27 October 2026

- **602 offline tests pass, zero skips** on the actual Pi 5 ARM64 / Python 3.13.5 /
  Tk 8.6 graphical session. The macOS run passes with 16 GUI tests skipped; the Pi
  covers those tests. The attached display is 1920×1200, Wayland/labwc, scale 1.
  The USB touchscreen is enumerated by the OS; generated touches, not physical
  finger/glove input, drive the automated workflows.
- Native fullscreen startup, Information/password pages and all six Settings
  pages are checked. Save/Cancel remain within the panel. Native captures are
  inspected, including station failures, crew selection and completion. Thirteen
  additional routine paths at the panel's actual resolution meet the normal
  3-tap report / 2-tap arrival, crew-change and completion budgets. The existing
  five-resolution, 65-path sweep and independent-group tests also pass.
- A short normal-event-loop sample renders 294 main-screen frames in ten seconds:
  2.30 ms p95 render-call time and 36.64 ms maximum nominal 20-ms heartbeat gap.
  Static-page repainting remains reduced. These are observations, not physical
  touch latency or compositor timing. See [measurement details](ui-performance.md#attached-panel-check--27-october-2026).
- An initial full run exposed a test-readiness race: the blocked-I/O driver
  attempted an action during a background history acknowledgement. It now waits
  for the local worker. Inspection also removed an unnecessary application lock
  and state rewrite for **maintenance-only** history results. Three new tests
  preserve newly staged data and require durable acknowledgement for real records
  and remote-ID links. The complete suite passes after those changes.
- Pillow's XWayland capture failed on this panel. All GUI capture drivers now
  share the documentation tool's region-only native Wayland fallback, with a
  bounded wait and explicit failure for blank/incomplete captures. Eight offline
  regressions cover boundaries, cleanup, failure handling and non-disclosure of
  subprocess diagnostics. Captures do not require a new application dependency.
- The test deployment uses disposable local-only data; network connections and
  update checks are disabled. Existing service configuration, runtime data and
  display modes are not modified. A disposable no-op service confirms the tested
  namespace sandbox settings are supported. No provider key, signing key or
  published artifact is used or changed. The version remains **1.2.0 development**.

Hardware/deployment observations remain separate from software-test success: the
Pi was already around 82°C before app launch, reached about 85°C during the suite,
and reported throttling flags. No thermal safeguard was disabled. Its enabled
service pointed to a missing deployment directory; an isolated source test does
not restore that production installation. See [startup diagnosis and safe panel
checks](pi-kiosk-hardening.md#checking-a-physical-panel-safely).

Physical touch/glove commissioning, audible sound output, production cooling,
multi-day endurance, power-loss recovery on target storage, compiled-release
acceptance and authorized real-service integration checks are still required.
This work does not certify an absence of bugs or vulnerabilities.

### Pi kiosk resource and security review — 27 October 2026

- **588 offline tests pass, zero skips** on Raspberry Pi 5 ARM64 / Python 3.13.5 /
  Tk 8.6 in a private virtual display. macOS passes with 16 graphical tests
  skipped, all covered on the Pi. The version remains 1.2.0 development.
- Nineteen new regressions cover malformed/oversized/non-finite/duplicate security
  JSON, unsafe throttle and audit paths, failed throttle clear, credential
  duplicate fields, rotation targets, HTTP-error response closure, a 500-preview
  sound burst, audio shutdown/start failures, static-page scheduling, immediate
  touch wake-up, hidden-layer suppression and device-care recovery. Already-private
  audit segments are not reopened for permission checks.
- Existing 65 touch-budget paths, 4,632 adaptive-layout cases, independent groups,
  restart/persistence, offline delivery and blocked-I/O responsiveness still pass.
  No connector mappings, reporting categories or durations are changed.
- **24,000 before/after dialog frames** show approximately 80–92% lower p95 render
  time for the measured pages. A native Information capture is pixel-identical.
  A further **9,000 grouped main-screen frames** have p95 0.811–1.530 ms and
  0–16 KiB RSS growth after warm-up. See [method and results](ui-performance.md#pi-kiosk-efficiency-review--27-october-2026).
- Ruff, whitespace and offline publication checks pass. Gitleaks reports no leaks
  in the reviewed tree or available history. All provider traffic is mocked or
  blocked; no customer credential, signing private key, installed kiosk, release
  artifact or update channel is changed. The isolated Pi workspace is removed.

An additional opt-in `ruff check --select S src scripts` produced 21 heuristic
findings, reviewed rather than silently suppressed: explicit no-shell process
launch/restart sites, build utilities resolved through the trusted OS PATH,
credential field/environment names and the deliberately public bootstrap,
URL requests validated before transport, and SQL composed only from fixed text
and bound-value placeholders. This is not a clean heuristic-scan claim.
Protect the deployment/build account and its PATH; application checks cannot
secure an attacker-controlled operating-system environment.

This closes reproduced weaknesses; it is not a comprehensive penetration test,
hardware endurance test or standards certification. Physical/glove usability,
power-loss/storage exercises and a representative multi-day soak are still
needed before release. [Deployment limits and checks](pi-kiosk-hardening.md).

### Low-tap operator workflows — 26 October 2026

- **569 offline tests pass, zero skips** on Raspberry Pi 5 ARM64 / Python 3.13.5 /
  Tk 8.6 in an isolated virtual display. The macOS run passes with 16 graphical
  tests skipped; those run on the Pi. Eleven added tests include ten real-file
  workflow regressions and the native touch-budget driver.
- **65 measured routine paths** cover single-station reporting with a reason,
  self-fix, Engineering request/arrival, join/leave including the last person,
  completion, handover and whole-line reporting at five viewports: 320×400,
  640×400, 800×480, 480×800 and 1920×1080. Report paths take at most 3 taps;
  the measured arrival/crew/completion paths take at most 2. Names/stations must
  be visible; multi-select, filtering and optional notes deliberately add taps.
- Hitboxes meet the 44-unit minimum, stay inside the viewport and do not overlap.
  All five failure reasons remain visible together. The map and primary workflow
  remain together on short screens. The adaptive sweep passes **4,632 cases**
  across 12 viewports, including single/batch crew layouts. Native screenshots
  were visually inspected.
- Failed direct reports restore the previous saved state and retain the draft.
  Failed quick crew changes reset selection before retry. Batch choices survive
  name/ID filtering; multi-station/group fault details, response identity and
  original start times survive the shortened paths. Independent-group and
  operator-handover drivers pass without real provider requests. Native checks
  additionally select people across a filtered 200-name roster and find a group
  before opening its report choices, without starting an incident prematurely.
- A further **9,000 rendering frames**, at synthetic 180-day animation phases,
  measured p95 **1.174 / 0.970 / 1.890 ms** at 800×480 / 480×800 / 1920×1080.
  RSS growth after warm-up was **16 / 0 / 0 KiB**. These are short observed runs,
  not proof of multi-day uptime or physical touchscreen responsiveness.
- Ruff, whitespace and offline publication audits pass. Gitleaks 8.30.1 reports
  no leaks in the reviewed source tree or its 17 available Git commits.
  No release, version bump,
  signing-key access or update-channel change is part of this work. No provider
  APIs or credentials were used; the installed Pi kiosk was not changed.

See the [operator touch-flow guide](operator-touch-flow.md) for steps, optional
paths, native images and commissioning limits. Site touch/glove acceptance,
hardware endurance, power-loss tests and authorized service acceptance remain
required before release; the checks do not establish an absence of all defects.

### Reliability and security follow-up — 26 October 2026

- **558 offline tests pass, zero skips** on Raspberry Pi 5 ARM64 / Python 3.13.5 /
  Tk 8.6, using a private virtual display. The macOS suite passes with 15 graphical
  tests skipped; the Pi covers those tests, including the **4,368 adaptive cases**
  and independent-group/operator handover touch workflows.
- New regressions reproduce outer-commit archive failures, failed dispatch saves,
  one-request-per-minute workflow delivery, interrupted paginated directories,
  automatic roster retry, ambiguous names, unnamed assignment, invalid remote IDs,
  guarded modal edits, worker-start failures and failed station-selection saves.
- A real-Tk test delays four local state writes by **800 ms each**, covering
  dispatch, acknowledgement and station/failure choices. All four run off Tk.
  One isolated Pi run measured **31.09 ms maximum heartbeat gap** during these
  delays, **29.61 ms** with a blocked simulated network request, no callback
  faults and no duplicate records. These are observed test results, not universal
  device-latency guarantees.
- Runtime JSON regressions cover oversized input, duplicate keys, non-finite
  numbers (including exponent overflow), excessive nesting, invalid state shapes,
  symlinks/hard links and unsafe connector-selection markers. See the
  [file-input boundaries](security.md#integrity-controls).
- A further **9,000 grouped-rendering frames** at synthetic 180-day phases have
  p95 frame times of **0.834–1.543 ms** and **0 KiB RSS growth after warm-up** across
  800×480, 480×800 and 1920×1080. See [performance evidence](ui-performance.md#recovery-and-slow-storage-follow-up--26-october-2026).
- Ruff, whitespace checks and the offline publication audit pass. Gitleaks 8.30.1
  reports no leaks in the reviewed working tree or available Git history. No real
  connector APIs, signing private keys, installed kiosk, release artifacts or
  update channel were used or changed. Temporary Pi testing files are removed.

The separate scan including local, ignored build records flagged 26 checksum
strings as generic keys. All were verified as SHA-256 entries in source manifests,
not credentials; those build records remain excluded from Git. No broad scanner
allowlist or credential deletion was used to hide findings.

This review closes reproduced defects; it does **not** certify absence of all
bugs or vulnerabilities. A physical touch/glove check, multi-day hardware soak,
power-loss/storage recovery exercise and authorized staging-service acceptance
are still required before a production v1.2.0 release. All existing documented
group-overlap, queue-capacity and downgrade boundaries continue to apply.

### Independent groups and local history — 25 October 2026

- **542 offline tests pass, zero skips** on Raspberry Pi 5 ARM64 / Python 3.13.5 /
  Tk 8.6, using a private virtual display. The macOS run passes its available
  tests with 15 graphical tests skipped because no display server is available.
- The existing **4,368 adaptive cases** remain covered. An additional real-Tk
  group driver checks **18 main/overview views at six viewport sizes**, from
  320×400 through 1920×1080 and 2560×720, for target bounds, minimum touch size
  and overlap. It reports and separately completes two incidents, reopens their
  focused responses, checks whole-line overlap feedback, and saves/reloads group
  configuration through the actual Settings form, including validation errors.
  Screenshot review caught and fixed a same-mode HD-to-small-screen column-width
  defect; the group driver now checks the editor remains usable after that resize.
- New persistence tests cover independent restart/release, multi-group incidents,
  legacy whole-line migration, topology-edit rejection, frozen connector routing,
  missing mappings, optional structured payloads, shared-asset Offline/Online
  sequencing and unrelated asset progress past a held write.
- History tests cover private permissions, hard links/symlinks, corrupt archive
  preservation, replay after interrupted acknowledgement, late remote IDs,
  full/failed staging, standalone incidents, background acknowledgements and
  pressure cleanup. Frequent writes cannot postpone maintenance indefinitely;
  protected old records cannot starve cleanup of eligible records.
- **9,000 measured grouped rendering frames** at synthetic 180-day phases record
  p95 frame times of **0.811–1.502 ms**, with **0–64 KiB RSS growth** after warm-up.
  Native screenshots use neutral fixtures, without credentials or desktop data.
  See [group previews](station-groups.md#native-kiosk-previews) and
  [renderer measurements](ui-performance.md#independent-groups--25-october-2026).
- Ruff, whitespace checks and the offline publication audit pass. All connector
  interactions use offline transports; interactive checks deny socket access.
  The installed kiosk, live providers, private keys, releases and signed channel
  are unchanged.

This is source-development verification, not release certification. Validate
physical touch/gloves, production-storage power loss, actual connector semantics
in an authorized staging system, and a multi-day hardware soak before deployment.
Active incidents are not mergeable: [overlap rules](station-groups.md#overlap-rule)
are an explicit operational boundary.

### Operator response and device care — 24 October 2026

- **504 offline tests pass, zero skips** on Raspberry Pi 5 ARM64 / Python 3.13.5 /
  Tk 8.6, on a private virtual display. The macOS run also passes its available
  tests; 14 graphical cases are skipped there without a display server.
- **4,368 adaptive screen/page cases** across 12 viewports pass touch-size,
  bounds and overlap checks. This includes operator self-fix, requested handover,
  fullscreen Settings, protected keyboards, page controls and unsaved edits.
- Actual touch-through checks complete both an operator-only incident and a
  same-record Engineering handover. Tests cover restart, queued offline delivery,
  failed-save rollback, repeated help requests, operator completion before help
  arrives, category/duration separation and the original elapsed timer.
- Device-care regressions cover pressure-driven retention, private permissions,
  symlinks, unrelated files, bounded inventory/rotation/queued payloads, slow and
  failed log writes, health-warning feedback and unavailable Linux sensors.
- **9,000 measured rendering frames**, at synthetic 180-day phases, record p95
  times of **0.929–1.823 ms** and **0 KiB RSS growth after warm-up** at three
  viewports. These are isolated renderer observations, not physical touch-latency
  guarantees or a substitute for a multi-day soak. See [performance](ui-performance.md).
- Native operator and Settings screenshots are refreshed with neutral fixtures.
  Ruff, whitespace checks and the offline publication audit pass. Provider
  sockets are blocked in interactive tests. No external API credentials,
  installed kiosk, release package, signing key or signed channel was changed.

The source remains **1.2.0 development** and the published channel remains 1.1.0.
Physical touchscreen/glove acceptance, power-loss testing on production storage,
a multi-day soak and compiled-release acceptance remain site/release checks.
See [operator self-fix](operator-self-fix.md) and
[automatic device-care boundaries](automatic-device-care.md).

### Durable delivery follow-up — 21 October 2026

- **475 offline tests pass, zero skips** on Raspberry Pi 5 ARM64 / Python 3.13.5 /
  Tk 8.6, in an isolated virtual display. This includes 32 journal regressions and
  a real-Tk blocked-network responsiveness test.
- **4,128 adaptive screen/page cases** across 12 viewports pass bounds,
  touch-size and target-intersection checks, including populated delivery-review
  panels and expired-help controls.
- Full report/repair/release and planned workflows run with no network, restart
  from actual state files, and drain through offline transports. Tests cover
  multiple incidents, lost creation responses, stable-key replay, unsafe-write
  holds, administrator linking, connector changes, queue capacity and local
  acknowledgement failures without retransmission.
- A deliberately stalled simulated write leaves Information, repair and release
  usable. The standalone Pi GUI run recorded 100 event-loop heartbeat samples,
  **70.17 ms maximum gap**, no duplicate records and no callback faults. This is
  an observation on that test display, not a latency guarantee for every device.
- **15,000 measured rendering frames** at three viewports use synthetic 180-day
  animation phases. p95 frame times are **0.914–1.803 ms**; RSS changes after warm-up
  are **0–80 KiB**. See [performance evidence](ui-performance.md).
- Lint, whitespace and the offline source/publication audit pass. No real provider
  API, signing key, installed kiosk, release artifact or signed channel was used
  or modified. Temporary Pi test tooling/data are removed after verification.

New workflow fields are not downgrade-compatible with older executables while
present. Review [delivery compatibility and recovery](offline-delivery.md) before
site trials. A physical multi-day soak and compiled-release acceptance are still
required before a v1.2.0 release; these tests do not establish years of uptime.

### Adaptive kiosk follow-up — 13 October 2026

- **442 offline tests pass, zero skips** on Raspberry Pi 5 ARM64 / Python 3.13.5 /
  Tk 8.6, in a private virtual display.
- **3,744 adaptive screen/page cases** across 12 viewport sizes pass bounds,
  minimum touch-size and target-intersection checks. Additional cases cover 103
  stations, short-screen navigation, install/rollback coexistence and unsaved
  Settings edits through repeated portrait/landscape resizing.
- The existing GUI suite also checks text overlap, click routing, password
  ownership, recovery and configuration saving, now including portrait, narrow,
  square-like and ultrawide layouts rather than only landscape screens.
- **9,000 measured animation frames** pass; warm-cache RSS growth was 0 KiB in
  each of three viewport runs. See [renderer measurements](ui-performance.md).
- Lint, whitespace and offline publication audits pass. No external-service API,
  signing key, installed kiosk or release channel was used or modified.

See [adaptive kiosk behavior and commissioning](adaptive-kiosk.md). Physical
touchscreen acceptance, a multi-day soak and compiled release acceptance remain
separate requirements before publishing v1.2.0.

### Initial rendering/request-budget checkpoint — 11 October 2026

Verified on 11 October 2026 (America/Toronto) in an isolated Raspberry Pi 5 ARM64
source workspace and private Xvfb display, with connector calls mocked or disabled.
The installed kiosk, signing keys, signed 1.1.0 channel and published downloads were
not changed. This is source-development verification, not signed-release acceptance.

| Check | Result and boundary |
| --- | --- |
| Complete ARM64 offline suite | **436 tests pass, zero skips** on Python 3.13.5 / Tk 8.6 |
| Touchscreen sweep | Main states, dialogs and persistent progress at 800×480, 1280×800, 1600×960 and 1920×1080; stacking checked in actual canvas display order |
| Settings | Single-instance panel, resizing while open, footer visibility, nested wizard input ownership, password-change return, valid/invalid API budgets and inherited default |
| Request policy | Budgets above 10, validation, exact rolling-window expiry, concurrent requests, live limit changes, connector replacement and diagnostic sharing |
| Rendering | Same-scene comparison averages 2.725 ms at 800×480 versus 15.890 ms with delete/recreate; detailed measurements in [UI performance](ui-performance.md) |
| Continuous-resource checks | 30,000-frame retained-renderer stress run; bounded image/scene/deadline caches; synthetic 180-day elapsed animation phase |
| Feedback/recovery | Accepted-touch acknowledgment, duplicate-operation guard, worker ownership, static-render recovery, slow-storage work off the GUI thread |
| Static checks | Ruff and diff whitespace checks; offline publication audit accepts source ahead of the unchanged signed channel |

No live connector API or release installation was tested for this development
version. A real multi-day soak on the target touchscreen, compiled-package testing,
and release/update acceptance are still required before releasing 1.2.0. The
virtual-display stress test is not evidence of months of physical kiosk operation.

</details>

## 1.1.0 — release verification (historical)

Verified on 29 September 2026 on Raspberry Pi 5, Raspberry Pi OS 64-bit
(Debian 13/Trixie), Python 3.13.5 and Tk 8.6. The graphical checks use private X11
displays at 96 DPI, without disturbing an existing kiosk. Connector transports are
offline test doubles; the compiled acceptance runs use a disabled, credential-free
connector and process-level network guards.

| Check | Result and boundary |
|---|---|
| Native offline suite | 410 tests pass on ARM64, zero skips; 53 additional regressions compared with 1.0.0 |
| Coverage | 83% overall measured source coverage, including the touchscreen subprocess; the CI minimum is 70% |
| Real state store | Completion, planned work, interrupted saves, queue recovery, and restarts use real state files |
| Completion evidence | Expired, rejected or evicted DONE updates never become a successful completion claim; positive evidence survives delayed notifications and restart |
| Confirmation timing | Duration ends at the affirmative confirmation touch, not the dialog opening or delayed background-worker start |
| Touchscreen sweep | Workflow states/dialogs and touch targets checked at 800×480, 1280×800, 1600×960 and 1920×1080; six Settings tabs and editable directory names covered |
| Compiled application | Native executable launched and clicked on private 800×480 and 1600×960 displays: main screen, Information, administrator identity/password, and Settings; Save/Cancel visible on the 7-inch layout |
| Signed upgrade and rollback | Actual 1.0.0 → 1.1.0 binary activation, automatic confirmation after the 120-second healthy-start dwell, same-version refusal, and idle rollback to 1.0.0; configuration, connector and saved state remain byte-for-byte unchanged |
| Native packaging | PyInstaller 6.21.0; exact 14-file source-free ARM64 bundle with disabled connector, MIT license, dependency notices, SBOM and checksums |
| Traceability | Final compiled-input fingerprint matches the private build source manifest; signed channel binds the executable and installation archive digests |
| Static checks | Ruff 0.16.9; Python compilation, shell syntax and publication gate |
| Documentation images | 22 application-generated images/animations updated for 1.1.0; no customer data or real connector responses |

Automated testing does not certify every site integration, display, audio device,
or operating-system image. The first-install bundle targets the OS generation
above; older OS images may require a native source build. See the site acceptance
requirements below.

## 1.0.0 (historical)

This records the scope and results of local version 1.0.0 verification. It is not
certification or a claim that every site integration has been tested. Tests use
in-memory transports; no customer credentials or external connector API calls are
required.

## Evidence and scope

| Check | Result and boundary |
|---|---|
| Raspberry Pi offline suite | 357 tests pass under Python 3.13.5 with a real Tk display server; zero skips |
| Coverage | 80% overall measured source coverage; the CI floor is 70%, not a claim of exhaustive testing |
| Compact GUI sweep | 64 workflow/dialog combinations, 1,616 dispatched touches, six Settings tabs, masked password change and cancel/return flow; no reported collision or callback fault |
| Responsive canvas | Actual requested window dimensions checked at 800×480, 1280×800, 1600×960 and 1920×1080 |
| Compiled application | Final native ARM64 build launched directly from a version slot on a private 1600×960 Pi X11 display: main screen, canonical update panel, protected Settings prompt and healthy startup checked; configuration/logs remain at the deployment root without a runtime override. Earlier acceptance also covered the attached 1440×716 display. |
| Documentation images | 22 real application captures/animations including password setup; main frames rendered natively at 1600×960, no upscaling; Settings captured at its own native dimensions |
| Static checks | Ruff, Python compilation, Linux shell syntax and local documentation-link checks pass |
| Secret scanning | Gitleaks 8.30.1, checksum-verified scanner; source, retained Git history and release text checked with redacted reports |
| Native packaging | PyInstaller 6.21.0; exact 14-file distribution; disabled credential-free connector; license, dependency notices, SBOM and checksums present |
| Integrity | Installation archive re-extracted into an empty directory; internal digests and executable permissions verified; signed channel binds the archive digest |
| Update integrity | USB archive re-extracted; Ed25519 signature and full executable checksum verified locally and on ARM64; same-version installation correctly refused |
| Traceability | Final compiled-input fingerprint matches the private build source manifest; release metadata and documentation are finalized separately |
| Multi-version behavior | 38 dedicated offline regressions cover selection, intermediates, conflicts, cache replay, bound approval, probation, recovery and bounded collections |
| Final hardening | Direct managed-executable data root, non-object/redacted HTTP errors, enforced offline transports, older-media rejection, authenticated staging recovery and pre-activation validation covered by regression tests |
| Distribution integrity | Public file/version/key/channel agreement, immutable CI action pins, bounded source-matched archive validation and eight audit regressions |
| Update endpoints | Regression tests pin the canonical repository, check both fetch paths with authenticated offline responses, reject signed cross-repository notes, and guard documented links |
| Settings credentials | Public initial password documented; per-installation change, restart/build preservation, old-password rejection for all protected actions, failed atomic writes, invalid files, throttling and authorization expiry covered offline |

These results describe local testing. They do not establish the availability of a
hosted release or the result of hosted CI. A reachable update channel is optional;
network errors do not interrupt line reporting. See
[update troubleshooting](update-user-guide.md).

## Site acceptance

- Commission the actual touch hardware, audio output, boot/autostart and operating
  system permissions. Automated X11 touches are not a human touchscreen trial.
- Validate the site's own connector mappings, permissions, remote idempotency and
  failure/recovery behavior with authorized non-production records first.
- Run a spare-terminal installation and physical USB upgrade/rollback trial before
  deploying future releases. Automated offline staging, activation and rollback
  tests are included, but are not a physical-drive/power-loss endurance test.
- Establish a unique site password, backups, network controls, retention policy,
  training and machine-safety procedures. Do not treat this console as a safety HMI.

The Pi verification used isolated user-owned tooling and temporary runtime data;
it did not require replacing the machine's OS or changing privileged installation
policy. macOS/Windows are source-supported targets, but new native releases for
those platforms were not built in this ARM64 verification pass.
