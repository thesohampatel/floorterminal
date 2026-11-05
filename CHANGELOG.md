# Changelog

This project follows semantic versioning for published releases.

## 1.2.2 — 5 November 2026

- Replace the persistent queued/review warning strip with a compact Delivery
  control and a destination-aware delivery centre.
- Add administrator-protected dismissal of held chat notices with retained audit
  evidence; incident and equipment updates cannot be dismissed.
- Expose retry for held help calls before expiry, refresh corrected recipient
  directories, and confirm help delivery only after its acknowledgement is saved.
- New support calls use the current connection independently of older incidents.
- Expire stale help even during outages/quota pauses and visibly disable new
  external support calls in standalone mode.
- Hold unexpected 2xx responses for review, avoiding duplicate writes caused by
  an incomplete connector success-code mapping.
- Distinguish actual local record references from ordinary `local:` message text.
- Use measured responsive cards for Information and Software Update content;
  keep detailed setup/support information in the Version tab.

See [v1.2.2 notes](docs/releases/v1.2.2.md). No deployment credentials or customer
configuration are distributed. Signed ARM64 installation and USB-update downloads
accompany this release; existing configuration and connectors are preserved.

## 1.2.1 — 4 November 2026

- Dedicated, fixed-width `HH:MM:SS` local-time display, separated from the line
  name and status notice in landscape, portrait and compact layouts.
- Familiar number/QWERTY rows, a separate complete symbol keyboard, balanced
  compact rows and consistent touch-key sizes; masked passwords and existing
  authorization rules are unchanged.
- Equal-size failure cards, including incomplete rows, and a separate fixed
  All/None/Find/page toolbar. Others and multi-selection remain available.
- Three optional, configurable message-only support shortcuts in Settings:
  independent labels, chat/person destinations and visibility. Existing routing
  remains the default; incident assignment and lifecycle messages are unchanged.
- In-bounds press compression, brief release feedback and contact acknowledgement
  using the existing repaint loop; bounded native button surfaces and callbacks.
- Shared rounded page headings, readable content sections, Information tabs for
  overview/license/safety and adaptive Software Update version cards/action rows.
- Regression coverage for layout, character reachability, custom support routing,
  disabled shortcuts, saved message destinations and version-independent fixtures.

Signed ARM64 installation and USB-update downloads accompany this release.
Existing v1.2.0 kiosks can upgrade normally without replacing their deployment
configuration or connectors. See [release notes](docs/releases/v1.2.1.md).

## 1.2.0

**Same-version reissue, 3 November 2026:** corrected the compiled Version panel's
development wording and capability catalogue, refreshed the complete Pi screenshot
gallery, and added release-metadata and data-preserving reinstall regressions.
The executable and checksums changed, not the version number. Existing 1.2.0
installations need the [documented administrative reinstall](docs/releases/v1.2.0-reissue.md),
not a normal USB upgrade. This is an explicit exception to the normal release policy.

### Added

- Independent production groups, group-only/whole-line stop scopes, concurrent
  incidents and per-group crews, timers, status and conveyor motion.
- Operator self-fix for permitted minor stoppages, with Engineering handover on
  the same response and original downtime timeline.
- Per-station failure catalogues with automatic Others, user-defined reasons,
  touch paging/search and preserved multi-selection.
- Private persistent crew rosters with daily idle-time refresh, manual Settings
  refresh and restart-safe cooldowns; normal picker openings make no directory calls.
- Standalone incident history and automatic bounded device care for logs/history,
  without deleting pending delivery or recovery data.

### Changed

- Configurable per-minute request budgets and one independent delivery worker.
  Local reporting remains available during network loss and rate limiting.
- Adaptive portrait/landscape/compact kiosk layouts, fullscreen protected pages,
  touch option sheets, persistent action feedback and reachable Settings footers.
- Routine 2–3 tap reporting and two-tap arrival, single-person crew edits and
  completion; optional details and multi-select remain available.
- Retained canvas items, bounded raster caches and motion phases, reduced redraws
  behind static pages, and cancellable Settings construction behind a loading cover.
- Optional schema-1 connector mappings for group assets/locations, structured
  diagnoses, keyed assignments and original event timestamps. Existing compatible
  connectors remain usable without replacing their credentials or configuration.

### Fixed

- Restart-safe delivery, acknowledgement retry and partial directory progress under
  low API budgets; incomplete/ambiguous remote results cannot become a complete list.
- Canvas-item churn during blink/wrap animation, hidden short-screen station
  actions, retained picker traces, and unnecessary empty-history state writes.
- Crew refresh cannot erase verified names on failure, change an open picker,
  cross connector/team identities or bypass server cooldowns through repeated taps.
- Documentation snapshots derive current/future versions from the package;
  installation instructions, operator paths and native screenshots match this version.
- The screenshot fixture implements the GUI health callback and refuses error-panel
  captures. CI installs the project's pinned development tools instead of keeping
  a second, outdated lint-version pin.

### Security and update safety

- Bounded strict JSON inputs, regular-file/permission checks, private runtime data,
  bounded audit/history housekeeping and closed failed HTTP responses.
- Real remote idempotency is required for replayable writes; ambiguous native
  writes remain held for protected reconciliation.
- USB updates validate detached runtime data, preserve compatible connectors and
  configuration extensions, retain private checkpoints and require a healthy GUI
  during probation. Active/pending work and unsafe downgrades block switching.
- Newer data is never deleted to force an older binary to run. See
  [upgrade precautions and limitations](docs/releases/v1.2.0.md) and the
  [dated verification evidence](docs/verification.md).

## 1.1.0

Reliability, clarity, and display-quality release. Upgrading from 1.0.0 needs no
configuration or connector changes, and an idle state file stays readable by
1.0.0, so one-touch rollback keeps working.

### Fixed

- **Repair and planned-work completion saved reliably.** `work_label` and
  `work_type` are now part of the validated state schema. Completing a repair, or
  starting and releasing planned Engineering work, no longer fails with
  "Persisted state contains unsupported fields".
- **No inconsistent state after a failed save.** Every save validates an isolated
  snapshot before an atomic write. If validation or the write fails, the live
  state is restored in place to the last saved snapshot. The screen can no longer
  show Production running while the file still says a repair is active, and one
  rejected value can no longer make station selection, crew confirmation,
  downtime recording, synchronization, and support calls fail afterwards.
- **Release time is not extended by a retry.** The operator's confirmation time
  is recorded first. If the release itself cannot be saved, a later confirmation
  (including after a restart) records the original release time. The
  micro-stop/downtime classification therefore does not change, and the dialog
  says which time will be recorded. The timestamp is captured on the affirmative
  confirmation touch, not when the dialog opens or a background worker starts.
- **Line release is one atomic transition.** The release, the queued
  response-record comment and DONE status, the asset Online state, and the
  completion notifications are committed in a single save before any network
  call. An interruption at any point leaves those updates queued for automatic
  retry instead of losing them.
- **Completion updates are always attempted.** Asset Online, the completion
  comment, DONE status, and completion chats are no longer skipped when an
  earlier step fails.
- **Truthful completion messages.** The status line in completion chats is built
  when the message is actually sent. It says "DONE update queued" or "ONLINE
  update queued" until those updates have really succeeded, instead of always
  claiming "DONE • ONLINE". If the DONE update expires or is abandoned, chats say
  "DONE not confirmed" rather than treating an empty queue as delivery evidence.
  Successful delivery evidence survives a restart while notifications are queued.
  Manual synchronization reports queue state without claiming discarded updates
  were delivered.
- **A queued DONE is not lost to the next incident.** Completion status updates
  have their own queue and are no longer overwritten when the next repair starts.
- **Specific, persistent error messages.** A failed touch action or operator
  operation opens a panel naming the operation (for example "Completing repair"),
  the error, and the saved line status. The panel stays until acknowledged. The
  animation loop can no longer paint over it, and a frame that cannot be drawn is
  held on a static explanation instead of freezing the kiosk.
- **Editable team and chat names.** Engineering team and chat or person names in
  Settings are free text with directory suggestions. Previously they became
  read-only as soon as a value was configured or a directory was loaded.
- **Settings usable on a 7-inch panel.** At 800 x 480, Save and Cancel and the
  station controls are no longer pushed off the window. Descriptions wrap to the
  window instead of being clipped.
- **Every documented template placeholder formats.** Placeholders accepted by
  Settings (such as `{time}` or `{work_label}` in the help message) no longer
  raise an error at send time.

### Added

- **Durable notification and record-update queues.** Lifecycle chats, support
  calls, response-record comments, and status changes are queued in the state
  file and retried with backoff. They are rescheduled from the connector's
  rate-limit delay (for example FloorTerminal's own 10 requests/minute budget),
  bounded in size, expired when stale, and audited when abandoned after
  permanent rejection. Requests for help are sent before other queued messages.
  A queued support call tells the operator it will be sent automatically.
- **Asset status notes.** Offline and Online asset statuses carry a
  plain-language note: the affected stations, the reported failure types, the
  operator's own "Others" description, and the response-record reference. The
  Online note also gives the classification and total line time. Wall-clock
  timestamps are left out because the status has its own start time. The note is
  sent through the connector's `status_description` field mapping.
- A header chip and manual retry for any queued external update.

### Display quality

- Rounded controls, cards, and circles are drawn with anti-aliased edges on
  Raspberry Pi and other X11 displays. This uses cached pre-rendered shapes with
  binary transparency, so frame cost is unchanged.
- Text size is pinned to the 96 DPI design scale on X11. A panel that reports its
  physical size no longer enlarges labels relative to their controls.
- Settings uses a flat, high-contrast theme with touch-sized tabs, fields,
  check boxes, list rows, and scroll bars, plus drag-to-scroll on every tab.

### Development

- Workflow tests run against the real state store and restart from the saved
  file, so a transition the validator rejects fails the suite. The touchscreen
  sweep also covers the error panel, the release note, editable directory names,
  and Settings on an 800 x 480 panel.
- The publication gate accepts a source version newer than the signed channel
  between releases, and still requires an exact match when auditing release
  artifacts.

## 1.0.0

First public open-source release of FloorTerminal.

- Deterministic newest-compatible selection across multiple signed USB packages,
  intermediate-version guidance, bounded versioned drive collections, conflict
  rejection, and authorization tied to the selected version and payload.
- Signed availability-cache verification after restart, replay/substitution checks,
  protected probation/restart transitions, and recovery that excludes failed or
  unconfirmed versions while retaining three installed slots.

- Reliability and security: consistent runtime data roots for directly launched
  managed executables; robust redacted connector errors; persistent signed staging
  with revalidation before activation; explicit older-media rejection; enforceable
  offline transport guards; immutable CI action pins; and a repeatable source,
  signing and native archive integrity checks.

- Corrected the immutable GitHub update endpoint and release/documentation links
  to the canonical `thesohampatel/floorterminal` repository. Added independent
  URL/transport/signature regressions and refreshed first-release artifacts
  without changing the signing identity or maintainer contact email.

- Native HD Raspberry Pi screenshots, a lossless operator walkthrough, actual
  conveyor-motion recording and detailed Settings screenshots; capture refuses
  upscaled or undersized output.
- Clean opaque modal backgrounds, complete station-number badges and better timer
  spacing. The line-down subtitle no longer claims a message was delivered when
  messaging may be disabled or queued.
- Disabled or incomplete connector drafts stay visible in Settings without
  incorrectly enabling external workflow and support buttons on the main screen.
- Build-input fingerprints with change-during-build detection, mandatory notices
  in signed USB update copies, normalized archive ownership, and checksum-pinned
  Gitleaks secret-scanning CI.

- Introduced the original FloorTerminal identity and application icon: a deliberate
  operator touch at the centre of the fault, report, response, and restored-flow
  lifecycle. The bundled vector master and raster application assets contain no
  third-party artwork.
- Corrected responsive scaling for canvas arcs and image coordinates, keeping status
  symbols, indicators, and the FloorTerminal mark aligned at every supported aspect
  ratio and display size.
- Build-history directories and files are now forced to owner-only permissions and
  symbolic-link roots are refused, matching the private-evidence boundary promised
  by the release documentation.
- Responsive Raspberry Pi/desktop touchscreen workflow for unplanned interruption
  reporting, planned Engineering work, responder participation, completion, support
  requests, escalation, and local-first recovery.
- Provider-neutral Connector v1 contract with isolated capabilities, strict HTTPS and
  host controls, independent degradation, request budgeting, safe diagnostics, field
  mapping, and remotely enforced create-operation idempotency.
- Configurable arbitrary stations with per-station failure choices and automatic
  **Others** context.
- Original MIT-licensed operational sound cues with safe asynchronous playback on
  Linux, macOS, and Windows.
- Atomic validated state/configuration, dated retained audit logs, storage checks,
  protected Settings/kiosk controls, accessible redundant status, and offline tests.
- Audited native release pipeline with source/secret/runtime exclusion, SPDX SBOM,
  notices, checksums, Raspberry Pi installer, graphical-session startup, and hardened
  user-systemd supervision.
- Signature-verified offline software updates: a non-blocking header indicator, a
  four-tab Software Update panel, USB update drives carrying a detached Ed25519
  manifest signature verified against build-time trust anchors, triple checksum
  verification before anything is copied, administrator-authorized activation,
  managed version slots switched by one atomic symbolic link, one-touch rollback,
  a supervised launcher that restores the previous version automatically when a new
  one cannot start, and update records on the terminal and on the drive. Deployment
  configuration, connector files, saved workflow state, and audit logs are never
  touched, so a terminal resumes exactly where it stopped.
- Maintainer release tooling for offline key generation, update-package signing, and
  generation of signed availability metadata.
- Application controller split into separately reviewable layers under
  `controller/` — workflow, dialogs, and software-update controls — composed onto
  the same class, so organisation changed and behaviour did not.
- System-clock plausibility check at startup, because every recorded time depends
  on a clock a Raspberry Pi cannot keep without network time.
- Software Update panel wording resolved through the locale catalogue, which grew
  from 44 to 99 keys; a test fails if any panel label does not resolve.
- Larger touch targets throughout: every control an operator uses during an incident
  now clears 9 mm on both supported panels, and no control is below 9 mm on the
  10.1-inch panel.
- Small coloured text is drawn in a readable darker variant of its own hue while
  status fills keep their separation.
- SPDX SBOM extended to the embedded CPython runtime and Tcl/Tk.
- Requirements traceability matrix, product lifecycle and defect-handling policy,
  and measured accessibility evidence.
- Contrast-aware control labels: a button label is drawn in the dark text colour
  wherever white would fall below the readable minimum on its own fill, which fixes
  the amber primary action and protects deployment-chosen custom palettes.
- Touchscreen regression sweep that renders every workflow state and dialog and
  presses every registered control, plus measured accessibility evidence.
- Raspberry Pi release preparation runs that sweep inside a private virtual display,
  supporting independently verified compact and HD viewports rather than silently
  letting fullscreen mode override the requested window dimensions.
- Fixed a crash when saving Settings while failure selections were recorded.
- Settings now uses the stable `ui_language` schema key rather than translated
  display text, so future locale names cannot break language selection. The GUI
  sweep also visits all six Settings tabs and rejects hidden or off-screen tabs.
- Connector wire-type mappings now preserve numeric identifiers where an external
  schema requires them; bounded cursor pagination covers every directory lookup;
  optional authenticated-account identity is data-driven; and declared safe
  transport retries are validated, bounded, logged, and charged to the rolling
  request budget.
- Repair, responder-assignment, completion, and Production-release transitions are
  persisted locally before non-create connector updates. Failed status, assignment,
  and asset updates remain visible and retryable without blocking the physical line
  workflow; asset retries preserve both their key and exact original payload.
- Offline-update verification now rejects small-order Ed25519 points and metadata
  predating its signing key. A failed availability refresh retains the last signed
  channel result while reporting that the latest check failed.
- Release-signing private material defaults to an owner-only directory outside the
  repository; the repository retains only public trust material.
- Comprehensive operator, configuration, connector, deployment, security, build,
  update, accessibility, governance, contributor, and support documentation.
