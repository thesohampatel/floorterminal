# Product lifecycle, defect handling, and patch management

This document states how the project is maintained over time. It exists because an
assessor, a customer's IT function, or a site quality manager will ask — and because
"how are defects handled" is a question the source tree cannot answer on its own.

It records a maintenance process. It is not a certification, a service-level
agreement, or a warranty; the [MIT License](../LICENSE) terms are unchanged.

## Supported versions

| Version line | Status | Security fixes | Notes |
|---|---|---|---|
| Latest release on `main` | Supported | Yes | The only line that receives fixes |
| Any earlier release | Unsupported | No | Update before deploying |

One line is supported at a time. A terminal can always fall back to the previously
installed version through the rollback path, but a rolled-back terminal is running an
unsupported version and should be returned to the supported one once the defect that
prompted the rollback is resolved.

## Defect handling

1. **Intake.** Non-sensitive defects arrive through GitHub Issues. Security defects
   use private vulnerability reporting as described in [`SECURITY.md`](../SECURITY.md)
   and never through a public issue.
2. **Triage.** Each report is classified by whether it can cause a lost or duplicated
   production record, an incorrect downtime figure, an unauthorized version or
   settings change, an unrecoverable terminal, or a workflow that cannot be
   completed. Anything in that set is handled before feature work.
3. **Reproduction.** A defect is not accepted as fixed without a failing offline test
   first. The touchscreen sweep and the update suites exist so that regressions in
   the operator path are reproducible without hardware.
4. **Fix and verification.** Lint, the full offline suite, the coverage gate, and the
   shell syntax checks all run in CI on every supported Python version.
5. **Release.** The change is described in [`CHANGELOG.md`](../CHANGELOG.md) with its
   operational effect. Application updates follow the documented
   [signed update mechanism](software-updates.md).
6. **Notification.** Deployers are told when a release carries a security fix, a
   migration requirement, or a credential-rotation requirement.

## Patch management for deployed terminals

Terminals are updated offline from signed removable media; see
[offline software updates](software-updates.md). The site owns the decision to apply
a release and the schedule for doing so.

- A terminal reports whether a newer version exists whenever it can reach the
  release channel, and reports plainly when it cannot.
- Nothing is installed without administrator authorization at the terminal.
- The previously accepted version stays installed for one-touch rollback, and a
  version that cannot start is restored automatically.
- Operating system, firmware, and dependency patching for the Raspberry Pi remain the
  deployment owner's responsibility and are outside this application's update path.

## End of life

When a version line is retired, the retirement is announced in the changelog and the
release notes, stating the final version, the reason, and the recommended successor.
Retirement removes maintenance, not function: an installed terminal keeps running,
and its recorded data stays readable, because state and logs are plain JSON and JSON
Lines with a documented schema version.

If the project itself is discontinued, the MIT License permits any deployer to
continue building, modifying, and distributing it. The reproducible items a successor
needs — build procedure, release audit, update signing tooling, and the schemas — are
all in this repository.

## Signing-key lifecycle

Terminals verify update signatures against public keys embedded at build time.
Only an already-trusted key can authorize an update; changing local configuration
cannot add trust. Loss of a signing key does not stop installed software or
rollback. If a trusted key is compromised, recovery needs an independently
verified installation rather than reliance on that key's signatures. See the
[trust model](threat-model.md) and [security policy](../SECURITY.md).

## Build identity and reproducibility

Builds are **not** bit-for-bit reproducible. PyInstaller embeds timestamps and
absolute build paths, and the frozen artifact varies with the exact interpreter,
Tcl/Tk, and operating-system libraries present on the build host. Rebuilding the same
commit produces a functionally identical artifact with a different SHA-256.

Build identity is therefore established by evidence rather than by re-derivation:

- an immutable build ID and UTC timestamp recorded for every attempt;
- the artifact SHA-256, the embedded profile hash, and the configuration hash bound
  into the generated notices;
- the release checksum manifest covering every delivered file;
- an SPDX SBOM naming the application, PyInstaller, the embedded CPython runtime, and
  Tcl/Tk;
- the Git revision and worktree cleanliness captured in the owner-side build record.

Verify a delivered artifact against the published digest and the release record, not
by rebuilding it and comparing hashes.
