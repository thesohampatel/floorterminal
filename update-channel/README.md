# Signed update availability

Deployed terminals read a signed document over HTTPS to check whether a newer
version is available. They never download an executable from this directory, and
the availability check cannot install software.

| File | Purpose |
|---|---|
| `latest.json` | Version, release details, compatibility, and archive digest |
| `latest.json.sig` | Detached Ed25519 signature over the exact document bytes |

The document and signature form one authenticated pair. Editing either file
invalidates verification. Runtime configuration cannot substitute a different
endpoint or public key.

If either file is missing, unreachable, or invalid, the update indicator reports
that availability could not be checked. This does not block line reporting, timers,
connectors, Settings, or independently verified USB updates.

The endpoint is fixed in the
[update trust policy](../src/floorterminal/update/trust.py).
See [the schema and verification rules](../docs/software-updates.md) or the
[operator update guide](../docs/update-user-guide.md).
