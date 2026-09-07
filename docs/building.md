# Native release builds

The automated builder validates configuration, the project profile,
`connector.json`, Python syntax, tests, Tk availability, disk space, host
architecture, legal assets, locale resources, and native build dependencies before
compiling. It then creates a minimal audited release and a permanent owner-side
build record. Packaged JSON locale catalogs and the complete allow-listed set of
original WAV sound cues and application identity PNGs are explicitly included in
PyInstaller output.

## Build on the target operating system

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install pyinstaller==6.21.0
python3 scripts/setup_runtime.py
./scripts/build/build.sh
```

The standard template uses the public initial password `admin@123`; users change it
in Settings after installation. Private custom builds can use a private profile or
an explicit environment placeholder; see [Project profile](project-profile.md).
Do not put private secrets in shell commands or tracked files.
On macOS ensure the native Python selected by
the launcher has Tk and the pinned PyInstaller installed.

On 64-bit Raspberry Pi OS, first install `python3-venv` and `python3-tk` with the
OS package manager, prepare the environment above, then use the release
wrapper instead of `build.sh`:

```bash
./scripts/install/prepare_release_on_pi.sh
```

It installs the reviewed ARM64 prerequisites and runs the builder inside a private
1920×1200 Xvfb session with TCP disabled. This is important over SSH: the real Tk
touchscreen sweep checks actual window sizes of 800×480, 1280×800, 1600×960 and
1920×1080, visits every
Settings tab, and rejects hidden or off-screen tab controls rather than being
skipped because the shell has no display. The virtual display is used only for
build-time verification; the installed kiosk still requires the normal graphical
session.

The copied example needs no password environment variable. The profile password
is converted to a salted PBKDF2 hash for the embedded application. Only the
deliberately public standard bootstrap password is disclosed in deployment
instructions; private build passwords remain excluded. Keep private profiles
outside source control. Never distribute an installation's `settings_auth.json`.

PyInstaller does not cross-compile operating systems or CPU architectures. Build
the Raspberry Pi executable on 64-bit Raspberry Pi OS (`aarch64`), the macOS app
on macOS, and the Windows executable on Windows. Provision the exact PyInstaller
version reported by the builder in a reviewed environment. The builder refuses to
download packages, never calls the configured integration, and does not create a ZIP.

## Profiles and outputs

`project_profile.example.json` is the neutral tracked template. The setup command
copies it to ignored `project_profile.json`. Fill approved identity/legal fields,
retain the public bootstrap password or use a private initial password, and select
alternate profiles through the build launcher. The builder embeds only a salted
PBKDF2 hash.

Every build is isolated under
`dist/releases/<distribution-profile>/<build-id>/floorterminal/`; repeated
builds never overwrite earlier release artifacts.

Each release contains the native application, project launcher icon, `config.json`,
disabled credential-free `connector.json`, `LICENSE`,
`SOFTWARE_INFORMATION_AND_NOTICES.txt`, an SPDX 2.3 SBOM, deployment instructions,
checksums, and applicable platform installer/autostart files. The audit rejects
source/bytecode, logs, runtime state, local credential verifiers, private plaintext passwords, enabled
integrations, and nonempty credentials. No service-specific integration artifacts
are produced.

The neutral connector demonstrates required idempotency declarations but is not evidence that deployed endpoints honor them. Before enabling response records or asset status, the deployment owner must map the external system's real header, query key, or unique body field and complete the corresponding commit-then-response-loss acceptance tests described in the connector guide.

## Build history

Every attempt creates `build_history/YYYY/MM/DD/<build-id>/build_record.json` plus a build log and appends `BUILD_HISTORY.jsonl`. Records capture release-profile/build identity, Git state, host, dependency versions, input, SBOM and artifact hashes, result, duration, and output. Failed attempts cannot claim stale artifacts.

`source_manifest.json` records SHA-256 for the application, packaged assets,
packaging, tests, scripts and tracked input templates. The builder refuses success
if those inputs change during compilation. Runtime config/profile digests are
recorded separately; neither their contents nor the Settings password is copied
into this manifest. All owner-side evidence remains private and ignored by Git.

Signed channel metadata, screenshots and release notes are necessarily completed
after compilation. If the public snapshot is finalized afterwards, compare its
`source_input_manifest()` result with the retained manifest to confirm that the
compiled inputs are identical. Preserve the original build-time Git revision and
dirty flag honestly; do not rewrite them to claim a later commit was compiled.

## Raspberry Pi deployment

Transfer the Linux release to the Pi and run its installer. Existing `/opt/floorterminal/config.json` and `connector.json` are preserved during upgrades. Complete the contract through protected Settings or a managed owner-only file, then restart. Tk needs a graphical display session; kiosk autostart hides normal desktop interaction.

The installer deploys `floorterminal.service` as a hardened per-user systemd service and keeps the XDG desktop entry only as a graphical-session trigger. `Restart=always` restores the kiosk after crashes or process exit. Escape, F11, and the window close control require administrator identification and password authorization; stopping the supervisor itself requires operating-system access with `systemctl --user stop floorterminal.service`.


For the supported installation and upgrade workflow, see
[Prebuilt Raspberry Pi installation](prebuilt-raspberry-pi.md) and the
[software update guide](update-user-guide.md).
