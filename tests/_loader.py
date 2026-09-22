"""Make ``tencent_asr/`` importable as a package for tests.

``tencent_asr/__init__.py`` imports ``provider``, which imports
``agent.transcription_provider`` — that only exists inside a live Hermes. So
the package is bound as a bare shell with the right ``__path__``, and the
modules that need the ABC get it from :mod:`_hermes_stubs`.
"""

from __future__ import annotations

import logging
import sys
import types
from pathlib import Path

PACKAGE = "tencent_asr"
ROOT = Path(__file__).resolve().parent.parent / PACKAGE


def load() -> types.ModuleType:
    existing = sys.modules.get(PACKAGE)
    if existing is not None:
        return existing
    logging.getLogger(PACKAGE).setLevel(logging.CRITICAL)
    module = types.ModuleType(PACKAGE)
    module.__path__ = [str(ROOT)]  # type: ignore[attr-defined]
    module.__package__ = PACKAGE
    sys.modules[PACKAGE] = module
    return module


tencent_asr = load()
