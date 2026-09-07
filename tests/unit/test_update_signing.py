import base64
import unittest

from floorterminal.update import signing, trust

# RFC 8032 section 7.1 Ed25519 test vectors: seed, public key, message, signature.
RFC_8032_VECTORS = (
    (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        (
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e0652249015"
            "55fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
        ),
    ),
    (
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        (
            "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69"
            "da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
        ),
    ),
    (
        "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
        "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        "af82",
        (
            "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3"
            "ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"
        ),
    ),
)


class Ed25519ConformanceTests(unittest.TestCase):
    def test_matches_rfc_8032_reference_vectors(self):
        for seed_hex, public_hex, message_hex, signature_hex in RFC_8032_VECTORS:
            with self.subTest(public_key=public_hex[:16]):
                seed = bytes.fromhex(seed_hex)
                public = bytes.fromhex(public_hex)
                message = bytes.fromhex(message_hex)
                signature = bytes.fromhex(signature_hex)
                self.assertEqual(signing.public_key_from_seed(seed), public)
                self.assertEqual(signing.sign(seed, message), signature)
                self.assertTrue(signing.verify(public, message, signature))

    def test_rejects_altered_message_signature_and_key(self):
        _, public_hex, _, signature_hex = RFC_8032_VECTORS[2]
        public = bytes.fromhex(public_hex)
        signature = bytes.fromhex(signature_hex)
        flipped = signature[:-1] + bytes([signature[-1] ^ 0x01])
        self.assertFalse(signing.verify(public, b"\xaf\x83", signature))
        self.assertFalse(signing.verify(public, b"\xaf\x82", flipped))
        self.assertFalse(signing.verify(bytes(32), b"\xaf\x82", signature))
        self.assertFalse(signing.verify(public, b"\xaf\x82", signature[:63]))
        self.assertFalse(signing.verify(public, b"\xaf\x82", signature + b"\x00"))
        self.assertFalse(signing.verify(public[:31], b"\xaf\x82", signature))
        self.assertFalse(signing.verify("not bytes", b"", signature))

    def test_rejects_out_of_range_scalar(self):
        """A signature whose scalar is not reduced must not be accepted."""
        _, public_hex, _, signature_hex = RFC_8032_VECTORS[1]
        signature = bytes.fromhex(signature_hex)
        unreduced = signature[:32] + (b"\xff" * 32)
        self.assertFalse(signing.verify(bytes.fromhex(public_hex), b"\x72", unreduced))

    def test_rejects_identity_and_small_order_encodings(self):
        identity = b"\x01" + (b"\x00" * 31)
        _, public_hex, _, signature_hex = RFC_8032_VECTORS[0]
        signature = bytes.fromhex(signature_hex)
        self.assertFalse(signing.verify(identity, b"", signature))
        self.assertFalse(
            signing.verify(bytes.fromhex(public_hex), b"", identity + signature[32:])
        )

    def test_key_and_signature_decoding_is_strict(self):
        _, public_hex, _, signature_hex = RFC_8032_VECTORS[0]
        public = bytes.fromhex(public_hex)
        encoded = base64.b64encode(public).decode("ascii")
        self.assertEqual(signing.decode_key(encoded), public)
        for bad in ("not base64!", base64.b64encode(b"short").decode(), ""):
            with self.subTest(value=bad), self.assertRaises(signing.SignatureError):
                signing.decode_key(bad)
        signature = base64.b64encode(bytes.fromhex(signature_hex)).decode("ascii")
        self.assertEqual(len(signing.decode_signature(signature)), 64)
        with self.assertRaises(signing.SignatureError):
            signing.decode_signature(base64.b64encode(b"too short").decode())

    def test_seed_length_is_enforced_for_signing(self):
        for bad in (b"", b"\x00" * 31, b"\x00" * 33):
            with self.subTest(length=len(bad)), self.assertRaises(signing.SignatureError):
                signing.sign(bad, b"message")


class TrustAnchorTests(unittest.TestCase):
    def test_every_compiled_trust_anchor_is_a_usable_curve_point(self):
        self.assertTrue(trust.TRUSTED_KEYS, "at least one release key must be trusted")
        for key in trust.TRUSTED_KEYS:
            with self.subTest(key_id=key.key_id):
                self.assertEqual(len(key.public_key), signing.PUBLIC_KEY_BYTES)
                self.assertIs(trust.trusted_key(key.key_id), key)
        self.assertIsNone(trust.trusted_key("0000000000000000"))

    def test_no_private_key_material_is_compiled_into_the_application(self):
        for key in trust.TRUSTED_KEYS:
            self.assertNotIn("private", key.comment.casefold())
            self.assertNotIn("seed", key.public_key_base64.casefold())


if __name__ == "__main__":
    unittest.main()
