"""TC3-HMAC-SHA256 request signing for Tencent Cloud.

Tencent's signature is a four-step derivation (date → service → tc3_request →
signature) over a canonical request. Getting any byte of the canonical form
wrong yields ``AuthFailure.SignatureFailure`` with no hint about which part, so
this module keeps the construction literal and heavily commented rather than
clever.

Ported from the OpenClaw plugin's ``src/audio.ts``.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Tuple

ALGORITHM = "TC3-HMAC-SHA256"
CONTENT_TYPE = "application/json; charset=utf-8"
SIGNED_HEADERS = "content-type;host"


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _hmac_sha256(key: bytes, data: str) -> bytes:
    return hmac.new(key, data.encode("utf-8"), hashlib.sha256).digest()


def utc_date(timestamp: int) -> str:
    """``YYYY-MM-DD`` in UTC — Tencent rejects a local-time date."""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")


def authorization_header(
    *,
    secret_id: str,
    secret_key: str,
    host: str,
    service: str,
    payload: str,
    timestamp: int,
) -> str:
    """Build the ``Authorization`` value for one request.

    ``payload`` must be the exact body string that will be sent — signing a
    re-serialized copy (different key order or spacing) breaks the signature.
    """
    date = utc_date(timestamp)

    canonical_request = "\n".join(
        [
            "POST",
            "/",
            "",  # no query string
            f"content-type:{CONTENT_TYPE}\nhost:{host}\n",
            SIGNED_HEADERS,
            _sha256_hex(payload),
        ]
    )

    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = "\n".join(
        [ALGORITHM, str(timestamp), credential_scope, _sha256_hex(canonical_request)]
    )

    secret_date = _hmac_sha256(f"TC3{secret_key}".encode("utf-8"), date)
    secret_service = _hmac_sha256(secret_date, service)
    secret_signing = _hmac_sha256(secret_service, "tc3_request")
    signature = hmac.new(
        secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    return (
        f"{ALGORITHM} Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={SIGNED_HEADERS}, Signature={signature}"
    )


def signed_headers(
    *,
    secret_id: str,
    secret_key: str,
    host: str,
    service: str,
    action: str,
    version: str,
    region: str,
    payload: str,
    timestamp: int,
) -> Tuple[dict, str]:
    """``(headers, payload)`` ready to POST. Returns the payload too, as a
    reminder that the signed bytes and the sent bytes must be identical."""
    return (
        {
            "Content-Type": CONTENT_TYPE,
            "Host": host,
            "X-TC-Action": action,
            "X-TC-Version": version,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Region": region,
            "Authorization": authorization_header(
                secret_id=secret_id,
                secret_key=secret_key,
                host=host,
                service=service,
                payload=payload,
                timestamp=timestamp,
            ),
        },
        payload,
    )
