# Security policy

## Supported versions

Security fixes are provided for the latest release on the maintained branch.
Older builds should be upgraded before deployment.

## Reporting a vulnerability

Do not open a public issue containing an exploit, credential, production URL,
personal data, or facility information. Use GitHub's private vulnerability
reporting feature for this repository. If it is unavailable, contact the
maintainer through the support route published in the repository profile and ask
for a private reporting channel without including sensitive details.

Include the affected version, platform, reproducible conditions, impact, and a
minimal proof of concept. Expect acknowledgement within seven calendar days.
Disclosure will be coordinated after a fix or mitigation is available.

## Software-update signing key

Offline software updates are authorized by an Ed25519 key whose public half is
compiled into every build. The private half is held offline by the maintainer and is
never present on a terminal, on an update drive, in a build environment, or in
continuous integration.

Report a suspected compromise of that key through the private channel above and mark
it urgent. Remediation is to publish a build whose `TRUSTED_KEYS` contains only a
replacement key, deploy it, and treat every package signed by the exposed key as
untrusted. Terminals keep running and can still roll back during that period; only
the ability to publish new updates is affected. Terminals cannot be told to trust a
new key remotely — a rotation must ship inside a build signed by the key it replaces.

## Scope and limitations

The application is an operational reporting aid, not a safety controller. Reports
about machine-control bypasses must identify whether the behavior belongs to this
project, the host operating system, or an external connector. Never test against a
production line or third-party service without explicit authorization.
