# Release verification — 1.0.0

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
