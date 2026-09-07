# Deployment profiles

`project_profile.json` is the neutral, open-source default profile. Optional deployment
profiles let maintainers produce clearly identified releases for a site, device
fleet, community edition, or downstream distribution without changing source code.

1. Copy `deployment.example.json` to a private location.
2. Set the product presentation, maintainer, distribution label, support contact,
   and Settings password.
3. Keep profiles containing plaintext passwords out of source control.
4. Run `scripts/build/build_profile.sh /path/to/deployment-profile.json`.

Every attempt receives an immutable build ID. Successful artifacts are written to:

    dist/releases/<distribution-profile>/<build-id>/floorterminal/

Credentials, runtime data, logs, and private profiles are never copied into a
release. The Settings password is embedded only as a salted PBKDF2 hash.
