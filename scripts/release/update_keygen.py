#!/usr/bin/env python3
"""Generate an offline Ed25519 release-signing key for software updates.

Run this on an offline maintainer workstation. The private seed authorizes every
future software update for every deployed terminal, so it must never be committed,
emailed, copied to an update drive, or stored on a Raspberry Pi.

    python3 scripts/release/update_keygen.py

Add the printed public key to ``TRUSTED_KEYS`` in
``src/floorterminal/update/trust.py``, then build and deploy that build
before the matching private key is used to sign anything: a terminal only trusts
keys that were compiled into the build it is already running.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from floorterminal.update import signing


def build_arguments():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        default="~/floorterminal_key",
        help="offline owner-only directory that receives private and public key files",
    )
    parser.add_argument(
        "--comment",
        default="Offline release-signing key",
        help="short description recorded with the key",
    )
    return parser.parse_args()


def main():
    arguments = build_arguments()
    directory = Path(arguments.output).expanduser()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    seed = secrets.token_bytes(signing.PRIVATE_SEED_BYTES)
    public = signing.public_key_from_seed(seed)
    if not signing.verify(public, b"key-self-test", signing.sign(seed, b"key-self-test")):
        raise SystemExit("Generated key failed its own signature self-test")
    key_id = hashlib.sha256(public).hexdigest()[:16]
    created = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    public_b64 = base64.b64encode(public).decode("ascii")

    document = {
        "schema_version": 1,
        "key_id": key_id,
        "algorithm": "ed25519",
        "created_utc": created,
        "public_key_base64": public_b64,
        "comment": arguments.comment,
    }
    public_path = directory / f"update-signing-{key_id}.public.json"
    private_path = directory / f"update-signing-{key_id}.private.json"
    public_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    descriptor = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(
            {**document, "private_seed_base64": base64.b64encode(seed).decode("ascii")},
            stream,
            indent=2,
        )
        stream.write("\n")

    print(f"Key id      : {key_id}")
    print(f"Public key  : {public_b64}")
    print(f"Created     : {created}")
    print(f"Public file : {public_path}")
    print(f"Private file: {private_path}  (mode 600)")
    print()
    print("Add this entry to TRUSTED_KEYS in src/floorterminal/update/trust.py:")
    print("    TrustedKey(")
    print(f'        key_id="{key_id}",')
    print(f'        public_key_base64="{public_b64}",')
    print(f'        valid_from_utc="{created}",')
    print(f'        comment="{arguments.comment}",')
    print("    ),")
    print()
    print("Move the private file to offline storage now. Terminals cannot be told to")
    print("trust a new key remotely; a rotation must ship inside a signed build first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
