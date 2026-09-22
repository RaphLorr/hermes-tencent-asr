"""Hermes plugin entry point: registers Tencent Cloud ASR as an STT provider.

Hermes finds a plugin by ``plugin.yaml`` + ``__init__.py`` at the directory
root and calls ``register(ctx)``, so these two files have to sit here.
Everything else lives in the :mod:`tencent_asr` package next to them.
"""

from .tencent_asr.plugin import register

__all__ = ["register"]
