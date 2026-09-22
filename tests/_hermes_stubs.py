"""Minimal stand-ins for the Hermes runtime so the provider is testable.

These mirror the contracts in ``agent/transcription_provider.py`` and
``agent/provider_base.py``; they are NOT the real implementations. Anything
that depends on real Hermes behaviour (the dispatcher, config resolution,
registration) has to be verified against a live gateway.
"""

from __future__ import annotations

import abc
import sys
import types
from typing import Any, Dict, List, Optional

_SCOPED_ENV: Dict[str, str] = {}


def set_env(**values: str) -> None:
    _SCOPED_ENV.update({k: str(v) for k, v in values.items()})


def clear_env() -> None:
    _SCOPED_ENV.clear()


def _module(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


def install() -> None:
    if "agent.transcription_provider" in sys.modules:
        return

    agent = _module("agent")
    agent.__path__ = []  # type: ignore[attr-defined]

    base = _module("agent.provider_base")

    class ProviderBase(abc.ABC):
        @property
        @abc.abstractmethod
        def name(self) -> str:
            ...

    class CatalogProviderBase(ProviderBase):
        @property
        def display_name(self) -> str:
            return self.name.title()

        def is_available(self) -> bool:
            return True

        def list_models(self) -> List[Dict[str, Any]]:
            return []

        def default_model(self) -> Optional[str]:
            models = self.list_models()
            return models[0].get("id") if models else None

    base.ProviderBase = ProviderBase
    base.CatalogProviderBase = CatalogProviderBase

    provider_mod = _module("agent.transcription_provider")

    class TranscriptionProvider(CatalogProviderBase):
        @abc.abstractmethod
        def transcribe(
            self,
            file_path: str,
            *,
            model: Optional[str] = None,
            language: Optional[str] = None,
            **extra: Any,
        ) -> Dict[str, Any]:
            ...

    provider_mod.TranscriptionProvider = TranscriptionProvider

    # gateway.platforms._shared.get_scoped_secret — the profile-scoped reader
    # settings.py prefers over os.environ.
    gateway = _module("gateway")
    gateway.__path__ = []  # type: ignore[attr-defined]
    platforms = _module("gateway.platforms")
    platforms.__path__ = []  # type: ignore[attr-defined]
    shared = _module("gateway.platforms._shared")

    def get_scoped_secret(name: str, default: Any = None, **_: Any) -> Any:
        return _SCOPED_ENV.get(name, default)

    shared.get_scoped_secret = get_scoped_secret
