"""The Hermes-facing provider: ``stt.provider: tencent``.

Contract (``agent/transcription_provider.py``):

* ``transcribe`` MUST NOT raise — every failure becomes the error envelope, or
  one bad clip takes down the turn that carried it.
* ``is_available`` MUST NOT raise and MUST NOT touch the network — Hermes calls
  it on every repaint of the model picker and of ``hermes setup``.
* Unknown ``**extra`` keys are ignored.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.transcription_provider import TranscriptionProvider

from . import resample, settings
from .audio_format import SUPPORTED_FORMATS, describe, format_for
from .client import AsrError, transcribe as call_tencent

logger = logging.getLogger(__name__)


def _error(message: str) -> Dict[str, Any]:
    return {
        "success": False,
        "transcript": "",
        "provider": settings.PROVIDER_NAME,
        "error": message,
    }


class TencentASRProvider(TranscriptionProvider):
    """Tencent Cloud SentenceRecognition (一句话识别).

    Chosen for WeChat voice notes specifically: it accepts **raw SILK**, which
    is what WeChat sends, so nothing has to be transcoded first. The trade-off
    is a hard 60s / 3MB ceiling — this API is for short clips, not recordings.
    """

    @property
    def name(self) -> str:
        return settings.PROVIDER_NAME

    @property
    def display_name(self) -> str:
        return "Tencent Cloud ASR"

    def is_available(self) -> bool:
        secret_id, secret_key = settings.credentials()
        return bool(secret_id and secret_key)

    def list_models(self) -> List[Dict[str, Any]]:
        """``EngSerViceType`` values, exposed as the model catalog.

        Only the ones the free tier covers are listed; Tencent has more
        (dialects, telephony) that need to be enabled on the account first.
        """
        return [
            {"id": "16k_zh", "display": "中文普通话 16k (general)"},
            {"id": "16k_zh_dialect", "display": "中文方言 16k"},
            {"id": "16k_en", "display": "English 16k"},
            {"id": "16k_yue", "display": "粤语 16k"},
        ]

    def default_model(self) -> Optional[str]:
        return settings.engine()

    def transcribe(
        self,
        file_path: str,
        *,
        model: Optional[str] = None,
        language: Optional[str] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        # `language` and `prompt` have no equivalent in SentenceRecognition —
        # the language IS the engine, and there is no vocabulary hint. Ignored
        # rather than rejected, per the ABC.
        del language, extra

        stt_config = None  # Hermes passes config through env/stt section only
        secret_id, secret_key = settings.credentials(stt_config)
        if not (secret_id and secret_key):
            return _error(
                f"{settings.env_name('secret_id')} / {settings.env_name('secret_key')} are not set"
            )

        try:
            audio = Path(file_path).read_bytes()
        except OSError as exc:
            return _error(f"could not read {file_path}: {exc}")

        voice_format = format_for(file_path, audio)
        if not voice_format:
            # Guessing here would be worse than failing: a wrong VoiceFormat
            # makes Tencent return confident nonsense rather than an error.
            return _error(
                f"unsupported audio format ({describe(file_path, audio)}); "
                f"SentenceRecognition accepts {', '.join(sorted(SUPPORTED_FORMATS))}"
            )

        engine = (model or "").strip() or settings.engine(stt_config)

        # Hermes hands us 24 kHz WAV for every WeChat voice note (pilk's
        # default), which no Tencent engine reads. Fix it before sending.
        prepared = resample.for_engine(audio, voice_format, engine)
        if prepared.notes:
            logger.info(
                "Tencent ASR adjusted %s: %s", Path(file_path).name, "; ".join(prepared.notes)
            )

        try:
            result = call_tencent(
                prepared.data,
                voice_format,
                secret_id=secret_id,
                secret_key=secret_key,
                region=settings.region(stt_config),
                engine=engine,
            )
        except AsrError as exc:
            suffix = f" (RequestId: {exc.request_id})" if exc.request_id else ""
            logger.warning("Tencent ASR failed: %s%s", exc, suffix)
            return _error(f"Tencent ASR: {exc}{suffix}")
        except Exception as exc:  # noqa: BLE001 — the ABC forbids raising
            logger.exception("Tencent ASR raised unexpectedly")
            return _error(f"Tencent ASR: unexpected failure: {exc}")

        logger.info(
            "Tencent ASR transcribed %s (%s, %dms, %d chars)",
            Path(file_path).name,
            voice_format,
            result.duration_ms,
            len(result.transcript),
        )
        return {
            "success": True,
            "transcript": result.transcript,
            "provider": settings.PROVIDER_NAME,
        }
