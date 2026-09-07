# Changelog

This project follows semantic versioning for published releases.

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
