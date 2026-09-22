"""TC3-HMAC-SHA256 signing.

This is the part most likely to be subtly wrong and the hardest to debug live:
Tencent answers a bad signature with ``AuthFailure.SignatureFailure`` and no
hint about which byte of the canonical request was off.

What these tests pin is the *shape* and the *sensitivity* of the derivation —
that the credential scope uses the UTC date, that the signed bytes are the sent
bytes, and that payload / timestamp / key / host each change the signature.
They do NOT prove the signature is one Tencent accepts; only a live call does
that, and the first real transcription is what confirms it.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _loader import load  # noqa: E402

load()

from tencent_asr.signing import (  # noqa: E402
    ALGORITHM,
    SIGNED_HEADERS,
    authorization_header,
    signed_headers,
    utc_date,
)

SECRET_ID = "AKIDz8krbsJ5yKBZQpn74WFkmLPx3EXAMPLE"
SECRET_KEY = "Gu5t9xGARNpq86cd98joQYCN3EXAMPLE"
HOST = "asr.tencentcloudapi.com"


class UtcDate(unittest.TestCase):
    def test_uses_utc_not_local_time(self):
        # 1758497400 is 2025-09-21T23:30Z, which is already the 22nd in +08:00.
        # Tencent verifies against UTC, so using local time here would put the
        # wrong date in the credential scope and fail the signature.
        self.assertEqual(utc_date(1758497400), "2025-09-21")

    def test_epoch(self):
        self.assertEqual(utc_date(0), "1970-01-01")


class AuthorizationHeader(unittest.TestCase):
    def _header(self, payload='{"a":1}', timestamp=1700000000):
        return authorization_header(
            secret_id=SECRET_ID,
            secret_key=SECRET_KEY,
            host=HOST,
            service="asr",
            payload=payload,
            timestamp=timestamp,
        )

    def test_shape(self):
        header = self._header()
        self.assertTrue(header.startswith(ALGORITHM + " "))
        self.assertIn(f"Credential={SECRET_ID}/", header)
        self.assertIn(f"SignedHeaders={SIGNED_HEADERS}", header)
        self.assertIn("Signature=", header)

    def test_signature_is_64_hex_chars(self):
        signature = self._header().split("Signature=")[1]
        self.assertEqual(len(signature), 64)
        int(signature, 16)  # raises if not hex

    def test_credential_scope_uses_the_utc_date(self):
        header = self._header(timestamp=1758497400)
        self.assertIn("2025-09-21/asr/tc3_request", header)

    def test_is_deterministic(self):
        self.assertEqual(self._header(), self._header())

    def test_payload_changes_the_signature(self):
        # The body is hashed into the canonical request, so signing a
        # re-serialized copy would silently produce a different signature.
        self.assertNotEqual(self._header(payload='{"a":1}'), self._header(payload='{"a":2}'))

    def test_timestamp_changes_the_signature(self):
        self.assertNotEqual(self._header(timestamp=1700000000), self._header(timestamp=1700000001))

    def test_secret_key_changes_the_signature(self):
        other = authorization_header(
            secret_id=SECRET_ID,
            secret_key="different",
            host=HOST,
            service="asr",
            payload='{"a":1}',
            timestamp=1700000000,
        )
        self.assertNotEqual(self._header(), other)

    def test_host_is_part_of_the_canonical_request(self):
        other = authorization_header(
            secret_id=SECRET_ID,
            secret_key=SECRET_KEY,
            host="other.tencentcloudapi.com",
            service="asr",
            payload='{"a":1}',
            timestamp=1700000000,
        )
        self.assertNotEqual(self._header(), other)


class SignedHeaders(unittest.TestCase):
    def test_returns_the_exact_payload_it_signed(self):
        payload = '{"VoiceFormat":"silk"}'
        headers, body = signed_headers(
            secret_id=SECRET_ID,
            secret_key=SECRET_KEY,
            host=HOST,
            service="asr",
            action="SentenceRecognition",
            version="2019-06-14",
            region="ap-shanghai",
            payload=payload,
            timestamp=1700000000,
        )
        self.assertEqual(body, payload, "the signed bytes must be the sent bytes")
        self.assertEqual(headers["X-TC-Action"], "SentenceRecognition")
        self.assertEqual(headers["X-TC-Version"], "2019-06-14")
        self.assertEqual(headers["X-TC-Region"], "ap-shanghai")
        self.assertEqual(headers["X-TC-Timestamp"], "1700000000")
        self.assertEqual(headers["Host"], HOST)
        self.assertIn("Authorization", headers)


if __name__ == "__main__":
    unittest.main()
