# Project profile

`project_profile.example.json` documents the immutable product and maintainer
information embedded during a native build. Deployments use an ignored private
copy named `project_profile.json`:

- product name, short name, and tagline;
- maintainer/copyright-holder name;
- distribution-profile label and support channel;
- fixed MIT license identity, summary, copyright, and open-source notice;
- initial password used to bootstrap operational Settings.

The tracked provider-neutral open-source profile attributes original development and
maintenance to Soham Patel and embeds the public support email shown in the
Information panel and release notices. Alternate distribution profiles may add an
approved distribution label and change the Settings password, but should preserve
upstream attribution and the MIT copyright notice. Validation requires
`license_name: MIT License` and `license_identifier: MIT`; a profile cannot convert a
build to a proprietary license.

The standard tracked template deliberately publishes the initial password
`admin@123`. Users change it in **Settings → System → Change Settings password**.
The builder embeds a uniquely salted PBKDF2-SHA256 verifier, not the plaintext
profile field. Documentation and deployment instructions explicitly disclose the
standard initial password; private custom passwords never belong in public files.

For a custom initial password, use a private profile's `settings_password`, or set
that field to `${FLOORTERMINAL_SETTINGS_PASSWORD}` and supply the environment
variable securely. The environment is read only for that explicit placeholder;
it does not silently override a literal profile password. An existing local
credential always takes precedence over either build password.

Runtime Settings cannot edit project identity or license information. Password
changes store only an owner-private salted verifier in `settings_auth.json` at the
runtime root, separate from config and the embedded profile. See
[Settings access](settings-access.md) for persistence, recovery and threat limits.

Do not place integration credentials or operational/personal data in the project
profile. External connection details belong only in protected `connector.json`
beside the deployed executable.
