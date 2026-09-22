"""One call to Tencent's SentenceRecognition, with the errors kept legible.

Synchronous on purpose: :meth:`TranscriptionProvider.transcribe` is a sync
method called off the event loop, so an async client here would only add a
loop to manage. ``urllib`` keeps the plugin dependency-free.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from . import settings
from .signing import signed_headers

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AsrResult:
    transcript: str
    duration_ms: int = 0
    request_id: str = ""


class AsrError(RuntimeError):
    """A refusal from Tencent, or a transport failure. ``code`` is theirs."""

    def __init__(self, message: str, *, code: str = "", request_id: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.request_id = request_id


def transcribe(
    audio: bytes,
    voice_format: str,
    *,
    secret_id: str,
    secret_key: str,
    region: str = settings.DEFAULT_REGION,
    engine: str = settings.DEFAULT_ENGINE,
    timeout: float = settings.DEFAULT_TIMEOUT_SECONDS,
) -> AsrResult:
    """Send one short clip and return what Tencent heard.

    Raises :class:`AsrError` for every failure mode; the provider converts that
    into Hermes' error envelope.
    """
    if not audio:
        raise AsrError("empty audio")
    if len(audio) > settings.MAX_AUDIO_BYTES:
        raise AsrError(
            f"audio is {len(audio) / 1024 / 1024:.1f}MB, over SentenceRecognition's "
            f"{settings.MAX_AUDIO_BYTES // 1024 // 1024}MB inline limit"
        )

    timestamp = int(time.time())
    # json.dumps once and sign THAT string: re-serializing would change key
    # order or spacing and invalidate the signature.
    payload = json.dumps(
        {
            "EngSerViceType": engine,
            "SourceType": settings.SOURCE_TYPE_INLINE,
            "VoiceFormat": voice_format,
            "Data": base64.b64encode(audio).decode("ascii"),
            "DataLen": len(audio),
        },
        ensure_ascii=False,
    )

    headers, body = signed_headers(
        secret_id=secret_id,
        secret_key=secret_key,
        host=settings.HOST,
        service=settings.SERVICE,
        action=settings.ACTION,
        version=settings.API_VERSION,
        region=region,
        payload=payload,
        timestamp=timestamp,
    )

    request = urllib.request.Request(
        f"https://{settings.HOST}",
        data=body.encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise AsrError(f"HTTP {exc.code} from Tencent ASR: {detail}") from exc
    except Exception as exc:
        raise AsrError(f"could not reach Tencent ASR: {exc}") from exc

    try:
        envelope = json.loads(raw).get("Response") or {}
    except ValueError as exc:
        raise AsrError(f"unparseable response: {raw[:200]}") from exc

    request_id = str(envelope.get("RequestId") or "")
    error = envelope.get("Error")
    if error:
        code = str(error.get("Code") or "")
        raise AsrError(
            f"{code}: {error.get('Message')}", code=code, request_id=request_id
        )

    return AsrResult(
        transcript=str(envelope.get("Result") or ""),
        duration_ms=int(envelope.get("AudioDuration") or 0),
        request_id=request_id,
    )
