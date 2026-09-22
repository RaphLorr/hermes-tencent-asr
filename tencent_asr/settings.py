"""Configuration for the Tencent ASR provider.

Credentials come from Hermes' profile-scoped secret store, never ``os.environ``
directly: one gateway process can serve several profiles, and a raw env read
would hand one profile's key to another.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

PROVIDER_NAME = "tencent"
ENV_PREFIX = "TENCENT_ASR"

# SentenceRecognition — 一句话识别. Short audio only; see MAX_* below.
HOST = "asr.tencentcloudapi.com"
SERVICE = "asr"
ACTION = "SentenceRecognition"
API_VERSION = "2019-06-14"
DEFAULT_REGION = "ap-shanghai"

# 16k_zh is the general Mandarin model and the one the free tier covers.
DEFAULT_ENGINE = "16k_zh"

# The prefix of an EngSerViceType is a contract, not a label: it tells Tencent
# what rate to read the samples at. Audio that disagrees is decoded at the
# wrong speed and comes back as an empty transcript with no error.
_ENGINE_SAMPLE_RATES = {"8k": 8000, "16k": 16000}

# SourceType 1 = audio inlined as base64 in the request body.
SOURCE_TYPE_INLINE = 1

# Tencent's limits for SentenceRecognition with inline data.
MAX_AUDIO_SECONDS = 60
MAX_AUDIO_BYTES = 3 * 1024 * 1024

DEFAULT_TIMEOUT_SECONDS = 30.0


def env_name(key: str) -> str:
    """``secret_id`` -> ``TENCENT_ASR_SECRET_ID``."""
    return f"{ENV_PREFIX}_{key.upper()}"


def _scoped(name: str) -> str:
    """Profile-scoped secret, with a plain-env fallback outside Hermes (tests)."""
    try:
        from gateway.platforms._shared import get_scoped_secret

        return str(get_scoped_secret(name, "") or "").strip()
    except Exception:
        import os

        return str(os.environ.get(name, "")).strip()


def _from_stt_config(stt_config: Optional[Dict[str, Any]], key: str) -> str:
    """``stt.providers.tencent.<key>`` from the config Hermes hands the provider."""
    if not isinstance(stt_config, dict):
        return ""
    providers = stt_config.get("providers")
    section = providers.get(PROVIDER_NAME) if isinstance(providers, dict) else None
    if not isinstance(section, dict):
        section = stt_config.get(PROVIDER_NAME)
    if not isinstance(section, dict):
        return ""
    return str(section.get(key) or "").strip()


def resolve(key: str, stt_config: Optional[Dict[str, Any]] = None, default: str = "") -> str:
    """Env wins over ``stt.providers.tencent.<key>``, mirroring Hermes' own
    precedence for platform settings."""
    return _scoped(env_name(key)) or _from_stt_config(stt_config, key) or default


def credentials(stt_config: Optional[Dict[str, Any]] = None) -> tuple:
    return resolve("secret_id", stt_config), resolve("secret_key", stt_config)


def region(stt_config: Optional[Dict[str, Any]] = None) -> str:
    return resolve("region", stt_config, DEFAULT_REGION)


def engine(stt_config: Optional[Dict[str, Any]] = None) -> str:
    return resolve("engine", stt_config, DEFAULT_ENGINE)


def engine_sample_rate(engine_name: str) -> Optional[int]:
    """``16k_zh`` -> ``16000``. ``None`` for a naming scheme we do not know.

    ``None`` means "leave the audio alone" rather than "assume 16k": Tencent
    adds engines, and resampling to a rate the engine does not want would turn
    a working clip into a broken one.
    """
    prefix = str(engine_name or "").split("_", 1)[0].strip().lower()
    return _ENGINE_SAMPLE_RATES.get(prefix)


def redact(secret: Optional[str]) -> str:
    """Credentials never reach a log line intact."""
    value = str(secret or "").strip()
    if not value:
        return "<unset>"
    return f"{value[:4]}…({len(value)} chars)"
