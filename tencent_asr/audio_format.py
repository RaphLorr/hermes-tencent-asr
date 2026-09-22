"""Decide what to tell Tencent this audio is.

``VoiceFormat`` is not a hint — a mismatch makes SentenceRecognition return
garbage or an error, so it has to be right. The filename is NOT trustworthy:
Hermes' unified media cache maps any unknown extension onto ``.ogg``, which is
exactly what happens to a WeChat voice note (raw SILK). So sniff the bytes
first and fall back to the extension only when nothing matches.

Formats SentenceRecognition accepts: wav, pcm, ogg-opus, speex, silk, mp3,
m4a, aac, amr.
"""

from __future__ import annotations

import os
from typing import Optional

# WeChat voice notes are SILK v3; the magic is ASCII and sometimes preceded by
# a single 0x02 byte that some clients prepend.
_SILK_MAGIC = b"#!SILK_V3"

# (offset, magic, VoiceFormat). Order matters only in that the first hit wins.
_MAGIC_TABLE = (
    (0, b"RIFF", "wav"),          # RIFF....WAVE
    (0, b"OggS", "ogg-opus"),     # Ogg container; Tencent's name for it
    (0, b"#!AMR", "amr"),
    (0, b"fLaC", None),           # recognised but unsupported — see below
    (0, b"ID3", "mp3"),
    (4, b"ftyp", "m4a"),          # ISO-BMFF: m4a/aac
)

_EXT_TO_FORMAT = {
    ".wav": "wav",
    ".pcm": "pcm",
    ".ogg": "ogg-opus",
    ".opus": "ogg-opus",
    ".speex": "speex",
    ".silk": "silk",
    ".mp3": "mp3",
    ".m4a": "m4a",
    ".aac": "aac",
    ".amr": "amr",
}

SUPPORTED_FORMATS = frozenset(_EXT_TO_FORMAT.values())


def sniff_format(data: bytes) -> Optional[str]:
    """Tencent ``VoiceFormat`` from the leading bytes, or ``None`` when unknown."""
    if not data:
        return None
    head = data[:16]
    # SILK may carry a one-byte prefix before the magic.
    if head.startswith(_SILK_MAGIC) or head[1:].startswith(_SILK_MAGIC):
        return "silk"
    for offset, magic, fmt in _MAGIC_TABLE:
        if head[offset : offset + len(magic)] == magic:
            return fmt
    # A bare MPEG frame sync has no ID3 tag.
    if head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "mp3"
    return None


def format_for(file_path: str, data: bytes) -> Optional[str]:
    """The format to send, preferring the bytes over the filename.

    Returns ``None`` when neither identifies something SentenceRecognition
    accepts — the caller should refuse rather than guess, because a wrong
    ``VoiceFormat`` produces confident nonsense rather than an error.
    """
    sniffed = sniff_format(data)
    if sniffed in SUPPORTED_FORMATS:
        return sniffed
    ext = os.path.splitext(file_path)[1].lower()
    return _EXT_TO_FORMAT.get(ext)


def describe(file_path: str, data: bytes) -> str:
    """One line for an error message: what we saw vs what the name claimed."""
    ext = os.path.splitext(file_path)[1].lower() or "<no extension>"
    sniffed = sniff_format(data) or "unrecognised"
    head = data[:8].hex() if data else ""
    return f"extension={ext} sniffed={sniffed} head={head}"
