"""``register(ctx)`` — the one thing Hermes calls.

Registering a provider is all this plugin does. It touches no core file and
adds no hook: ``stt.provider: tencent`` is what routes transcription here, and
Hermes' own dispatcher (``tools/transcription_command.py``) handles everything
around it — availability checks, error envelopes, the size cap.

Two rules from that dispatcher are worth remembering when editing the provider:

* a **built-in** provider name is rejected at registration, so this must not be
  called ``local``, ``local_command``, ``groq`` or ``openai``;
* a ``stt.providers.tencent: {type: command}`` entry in config would **win**
  over this plugin — command providers take precedence by design.
"""

from __future__ import annotations

import logging
from typing import Any

from .provider import TencentASRProvider

logger = logging.getLogger(__name__)


def register(ctx: Any) -> None:
    ctx.register_transcription_provider(TencentASRProvider())
    logger.debug("Registered Tencent Cloud ASR as an STT provider")
