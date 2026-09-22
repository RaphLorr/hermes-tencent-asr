"""Make a WAV match the engine, because ``EngSerViceType`` is a promise.

``16k_zh`` does not *describe* the audio — it tells SentenceRecognition to read
it as 16 kHz. Hand it 24 kHz and Tencent walks the samples at the wrong speed:
no error, a plausible ``AudioDuration``, and an empty ``Result``.

That is not a hypothetical. Hermes decodes WeChat's SILK with
``pilk.silk_to_wav(src, dst)`` and never passes a rate, so pilk's default wins::

    def silk_to_wav(silk: str, wav: str, rate: int = 24000):

Every WeChat voice note therefore arrives here at 24 kHz, which matches neither
of the two rates Tencent's engines accept.

Only WAV is touched. SILK, mp3, amr and friends go through byte-for-byte —
their rate lives inside a container this module does not parse, and a wrong
guess is worse than no guess.
"""

from __future__ import annotations

import logging
from array import array
from dataclasses import dataclass
from typing import List, Optional, Tuple

from . import settings, wav

logger = logging.getLogger(__name__)

# Below a quarter of full scale, the extra headroom buys nothing and some ASR
# front-ends quantise the quiet end away. 24 kHz WeChat notes have landed here
# around 550/32767 (-35 dBFS), which is faint enough to be worth lifting.
QUIET_PEAK = wav.FULL_SCALE // 4

# Half of full scale. Deliberately not 1.0: speech is peaky, and clipping the
# transients is a worse trade than a few dB of headroom.
TARGET_PEAK = wav.FULL_SCALE // 2

# ~+26 dB. Past this we would be amplifying the noise floor, not the voice.
MAX_GAIN = 20.0


@dataclass(frozen=True)
class Prepared:
    """Bytes to send, plus what was changed — ``notes`` is empty when nothing was."""

    data: bytes
    notes: Tuple[str, ...] = ()


def for_engine(data: bytes, voice_format: str, engine: str) -> Prepared:
    """Return audio the engine can read, never raising.

    A failure here must not cost the transcription: the original bytes are
    already what every earlier version sent, so falling back to them is safe.
    """
    try:
        return _prepare(data, voice_format, engine)
    except Exception:  # noqa: BLE001 — a bad clip must not break the turn
        logger.exception("Could not prepare audio for %s; sending it unchanged", engine)
        return Prepared(data)


def _prepare(data: bytes, voice_format: str, engine: str) -> Prepared:
    if voice_format != "wav":
        return Prepared(data)

    target_rate = settings.engine_sample_rate(engine)
    if not target_rate:
        logger.debug("No documented sample rate for engine %r; leaving the WAV alone", engine)
        return Prepared(data)

    audio = wav.decode(data)
    if audio is None or not audio.samples:
        return Prepared(data)

    notes: List[str] = []

    if audio.rate != target_rate:
        notes.append(f"resampled {audio.rate}Hz -> {target_rate}Hz for {engine}")
        audio = wav.WavAudio(
            rate=target_rate,
            samples=_resampled(audio.samples, audio.rate, target_rate),
        )

    audio, gain_note = _leveled(audio)
    if gain_note:
        notes.append(gain_note)

    if not notes:
        # Byte-identical output; re-encoding would only risk losing a chunk the
        # original carried and this module does not write back.
        return Prepared(data)
    return Prepared(wav.encode(audio), tuple(notes))


# --------------------------------------------------------------------- level


def _leveled(audio: wav.WavAudio) -> Tuple[wav.WavAudio, Optional[str]]:
    """Lift a faint recording toward ``TARGET_PEAK``; leave a healthy one alone."""
    peak = audio.peak
    if peak == 0:
        return audio, f"audio is digitally silent ({audio.seconds:.1f}s of zeros)"
    if peak >= QUIET_PEAK:
        return audio, None

    gain = min(TARGET_PEAK / peak, MAX_GAIN)
    note = f"amplified {gain:.1f}x (peak was {peak}/{wav.FULL_SCALE})"
    return wav.WavAudio(rate=audio.rate, samples=_amplified(audio.samples, gain)), note


def _amplified(samples: array, gain: float) -> array:
    return array("h", [_clamped(int(sample * gain)) for sample in samples])


def _clamped(value: int) -> int:
    return max(wav.MIN_SAMPLE, min(wav.MAX_SAMPLE, value))


# ---------------------------------------------------------------------- rate


def _resampled(samples: array, from_rate: int, to_rate: int) -> array:
    """Convert the sample rate. Pure Python on purpose — see the module note.

    ``audioop`` would be faster, but it is deprecated in 3.11 and gone in 3.13,
    and this plugin's whole appeal is that it installs with no dependencies.
    Sixty seconds of audio — SentenceRecognition's ceiling — costs well under
    the round trip to Tencent that follows it.
    """
    if from_rate == to_rate or not samples:
        return samples
    ratio = from_rate / to_rate
    return _averaged(samples, ratio) if ratio > 1 else _interpolated(samples, ratio)


def _averaged(samples: array, ratio: float) -> array:
    """Downsample by averaging each output sample's window of input samples.

    The averaging *is* the anti-alias filter: plain decimation (or the linear
    interpolation ``audioop.ratecv`` does) folds everything above the new
    Nyquist back down into the speech band. Going 24 kHz -> 16 kHz that is
    8–12 kHz landing on top of 4–8 kHz, which is where fricatives live.
    """
    count = int(len(samples) / ratio)
    # Precomputed from the index rather than accumulated, so float error cannot
    # drift over a long clip.
    bounds = [int(index * ratio) for index in range(count + 1)]
    return array("h", [_window_mean(samples, start, stop) for start, stop in zip(bounds, bounds[1:])])


def _window_mean(samples: array, start: int, stop: int) -> int:
    stop = min(max(stop, start + 1), len(samples))
    window = samples[start:stop]
    return sum(window) // len(window)


def _interpolated(samples: array, ratio: float) -> array:
    """Upsample by linear interpolation; no filter needed going up."""
    count = int(len(samples) / ratio)
    return array("h", [_lerp(samples, index * ratio) for index in range(count)])


def _lerp(samples: array, position: float) -> int:
    left = int(position)
    right = min(left + 1, len(samples) - 1)
    weight = position - left
    return int(samples[left] + (samples[right] - samples[left]) * weight)
