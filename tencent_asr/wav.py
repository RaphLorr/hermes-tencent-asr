"""Read and write the 16-bit PCM WAV that SentenceRecognition expects.

Only the subset Hermes actually produces is handled — uncompressed PCM through
the stdlib ``wave`` module. Anything else (a-law, 24-bit, a header this cannot
parse) comes back as ``None`` so the caller sends the original bytes untouched
rather than corrupting them.

Samples are kept in an ``array("h")`` rather than raw ``bytes`` because every
operation downstream is per-sample arithmetic, and because ``array`` makes the
endianness explicit: WAV is little-endian on the wire whatever the host is.
"""

from __future__ import annotations

import io
import logging
import sys
import wave
from array import array
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# The only width Tencent documents for pcm/wav, and the only one pilk emits.
SAMPLE_WIDTH_BYTES = 2

MIN_SAMPLE = -32768
MAX_SAMPLE = 32767
FULL_SCALE = MAX_SAMPLE

_HOST_IS_BIG_ENDIAN = sys.byteorder == "big"


@dataclass(frozen=True)
class WavAudio:
    """Mono 16-bit samples plus the rate they are meant to be played at."""

    rate: int
    samples: array

    @property
    def seconds(self) -> float:
        return len(self.samples) / self.rate if self.rate else 0.0

    @property
    def peak(self) -> int:
        """Largest absolute sample. ``0`` means digital silence.

        Taken as two C-level passes instead of ``max(abs(s) for s in ...)``,
        which is an order of magnitude slower over a minute of audio.
        """
        if not self.samples:
            return 0
        return max(max(self.samples), -min(self.samples))


def decode(data: bytes) -> Optional[WavAudio]:
    """Parse WAV bytes into mono 16-bit samples, or ``None`` if unsupported."""
    try:
        with wave.open(io.BytesIO(data)) as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.readframes(handle.getnframes())
    except Exception:
        # Not a failure worth surfacing: the caller falls back to the original
        # bytes, which is exactly what happened before this module existed.
        logger.debug("Not a WAV this plugin can rewrite", exc_info=True)
        return None

    if width != SAMPLE_WIDTH_BYTES or channels < 1 or rate <= 0:
        logger.debug(
            "WAV is %d-bit / %d channel(s) / %dHz — left untouched", width * 8, channels, rate
        )
        return None

    samples = _from_frames(frames, channels)
    return WavAudio(rate=rate, samples=_mixed_to_mono(samples, channels))


def encode(audio: WavAudio) -> bytes:
    """Serialise back to a mono 16-bit WAV."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(SAMPLE_WIDTH_BYTES)
        handle.setframerate(audio.rate)
        handle.writeframes(_to_frames(audio.samples))
    return buffer.getvalue()


def _from_frames(frames: bytes, channels: int) -> array:
    samples = array("h")
    # A truncated final frame would desynchronise the channel interleave.
    stride = SAMPLE_WIDTH_BYTES * channels
    usable = len(frames) - (len(frames) % stride)
    samples.frombytes(frames[:usable])
    if _HOST_IS_BIG_ENDIAN:
        samples.byteswap()
    return samples


def _to_frames(samples: array) -> bytes:
    if not _HOST_IS_BIG_ENDIAN:
        return samples.tobytes()
    swapped = array("h", samples)
    swapped.byteswap()
    return swapped.tobytes()


def _mixed_to_mono(samples: array, channels: int) -> array:
    """Average the interleaved channels. Tencent takes mono only."""
    if channels == 1:
        return samples
    return array(
        "h",
        [
            sum(samples[offset : offset + channels]) // channels
            for offset in range(0, len(samples), channels)
        ],
    )
