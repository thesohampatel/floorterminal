# Public update-verification keys

This directory contains public Ed25519 key descriptors. They are safe to distribute
and do not grant permission to sign software.

The application verifies update signatures against the trusted public keys embedded
in [the update trust policy](../src/floorterminal/update/trust.py). It does not load
keys from this directory at runtime. Adding or replacing a JSON file beside the
application cannot change which updates it trusts.

Private signing material is not part of the source, application bundle, connector
configuration, or update drive. Operators never need a private signing key.

See [update security and formats](../docs/software-updates.md) for the verification
contract and [the update guide](../docs/update-user-guide.md) for installation.
