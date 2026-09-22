"""Rate matching and levelling.

The bug being pinned: Hermes decodes WeChat SILK with ``pilk.silk_to_wav``,
whose ``rate`` defaults to 24000 and which Hermes never overrides. Sent to
``16k_zh``, Tencent reads those samples at 16 kHz — no error, correct-looking
duration, empty transcript.

So the tests care about two things above all: that a 24 kHz WAV comes out at
the engine's rate, and that anything this module does not understand comes out
byte-identical.
"""

import math
import sys
import unittest
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _loader import load  # noqa: E402

load()

from tencent_asr import resample, wav  # noqa: E402

SILK = b"#!SILK_V3" + b"\x00" * 64


def tone(rate, seconds=0.5, hz=1000, amplitude=12000, channels=1):
    """A sine as a WAV — loud enough that levelling leaves it alone."""
    count = int(rate * seconds)
    samples = array(
        "h",
        [
            int(amplitude * math.sin(2 * math.pi * hz * index / rate))
            for index in range(count)
            for _ in range(channels)
        ],
    )
    return _encode(rate, samples, channels)


def _encode(rate, samples, channels=1):
    import io
    import wave as wave_mod

    buffer = io.BytesIO()
    with wave_mod.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    return buffer.getvalue()


def dominant_hz(audio):
    """Roughly where the energy is, by counting zero crossings.

    Enough to tell a resample that preserved the signal from one that turned it
    into aliased mush; a real spectral test would need numpy.
    """
    samples = audio.samples
    crossings = sum(
        1
        for index in range(1, len(samples))
        if (samples[index - 1] < 0) != (samples[index] < 0)
    )
    return crossings / 2 / audio.seconds if audio.seconds else 0


class Container(unittest.TestCase):
    def test_round_trip_preserves_rate_and_samples(self):
        original = wav.decode(tone(16000))
        restored = wav.decode(wav.encode(original))
        self.assertEqual(restored.rate, original.rate)
        self.assertEqual(restored.samples, original.samples)

    def test_stereo_is_mixed_to_mono(self):
        audio = wav.decode(tone(16000, channels=2))
        self.assertEqual(len(audio.samples), int(16000 * 0.5))

    def test_unparseable_bytes_are_not_a_wav(self):
        self.assertIsNone(wav.decode(SILK))
        self.assertIsNone(wav.decode(b""))

    def test_peak_of_silence_is_zero(self):
        self.assertEqual(wav.decode(tone(16000, amplitude=0)).peak, 0)

    def test_seconds_matches_the_sample_count(self):
        self.assertAlmostEqual(wav.decode(tone(16000, seconds=1.25)).seconds, 1.25, places=3)


class EngineRate(unittest.TestCase):
    """The core fix: 24 kHz in, the engine's rate out."""

    def test_the_real_case_24k_becomes_16k(self):
        prepared = resample.for_engine(tone(24000), "wav", "16k_zh")
        self.assertEqual(wav.decode(prepared.data).rate, 16000)

    def test_duration_survives_the_conversion(self):
        prepared = resample.for_engine(tone(24000, seconds=5.0), "wav", "16k_zh")
        self.assertAlmostEqual(wav.decode(prepared.data).seconds, 5.0, places=2)

    def test_the_signal_survives_the_conversion(self):
        # 1 kHz in should still be about 1 kHz out — not aliased noise.
        prepared = resample.for_engine(tone(24000, hz=1000), "wav", "16k_zh")
        self.assertAlmostEqual(dominant_hz(wav.decode(prepared.data)), 1000, delta=60)

    def test_an_8k_engine_gets_8k_audio(self):
        prepared = resample.for_engine(tone(24000), "wav", "8k_zh")
        self.assertEqual(wav.decode(prepared.data).rate, 8000)

    def test_upsampling_works_too(self):
        prepared = resample.for_engine(tone(8000), "wav", "16k_zh")
        self.assertEqual(wav.decode(prepared.data).rate, 16000)
        self.assertAlmostEqual(dominant_hz(wav.decode(prepared.data)), 1000, delta=60)

    def test_matching_audio_is_returned_byte_identical(self):
        data = tone(16000)
        prepared = resample.for_engine(data, "wav", "16k_zh")
        self.assertIs(prepared.data, data)
        self.assertEqual(prepared.notes, ())

    def test_the_note_names_both_rates(self):
        prepared = resample.for_engine(tone(24000), "wav", "16k_zh")
        self.assertIn("24000Hz -> 16000Hz", prepared.notes[0])


class LeftAlone(unittest.TestCase):
    """Everything this module cannot read must pass straight through."""

    def test_silk_is_untouched(self):
        prepared = resample.for_engine(SILK, "silk", "16k_zh")
        self.assertIs(prepared.data, SILK)
        self.assertEqual(prepared.notes, ())

    def test_pcm_is_untouched_because_it_carries_no_rate(self):
        raw = b"\x00\x01" * 1000
        self.assertIs(resample.for_engine(raw, "pcm", "16k_zh").data, raw)

    def test_an_unknown_engine_leaves_the_audio_alone(self):
        data = tone(24000)
        self.assertIs(resample.for_engine(data, "wav", "myst_zh").data, data)

    def test_a_wav_label_on_non_wav_bytes_does_not_corrupt_them(self):
        self.assertIs(resample.for_engine(SILK, "wav", "16k_zh").data, SILK)

    def test_empty_audio_is_untouched(self):
        self.assertIs(resample.for_engine(b"", "wav", "16k_zh").data, b"")

    def test_never_raises(self):
        for payload in (b"", b"RIFF", b"RIFF\x00\x00\x00\x00WAVE", SILK, tone(24000)[:40]):
            try:
                resample.for_engine(payload, "wav", "16k_zh")
            except Exception as exc:  # pragma: no cover
                self.fail("for_engine raised on %r: %r" % (payload[:8], exc))


class Level(unittest.TestCase):
    def test_a_faint_recording_is_amplified(self):
        # 554/32767 is what a real WeChat note measured at.
        prepared = resample.for_engine(tone(16000, amplitude=554), "wav", "16k_zh")
        self.assertGreater(wav.decode(prepared.data).peak, resample.QUIET_PEAK)

    def test_the_gain_is_capped(self):
        # Peak 1 would need 16384x to reach the target; the cap stops at 20x,
        # because past that there is no voice left to lift, only noise.
        prepared = resample.for_engine(tone(16000, amplitude=1), "wav", "16k_zh")
        self.assertEqual(wav.decode(prepared.data).peak, int(resample.MAX_GAIN))

    def test_a_healthy_recording_is_not_touched(self):
        data = tone(16000, amplitude=20000)
        self.assertIs(resample.for_engine(data, "wav", "16k_zh").data, data)

    def test_silence_is_reported_not_amplified(self):
        prepared = resample.for_engine(tone(16000, amplitude=0), "wav", "16k_zh")
        self.assertEqual(wav.decode(prepared.data).peak, 0)
        self.assertIn("silent", prepared.notes[0])

    def test_amplifying_never_wraps_around(self):
        # Clamping, not overflow: a wrapped sample is a loud click.
        loud = array("h", [30000, -30000] * 100)
        amplified = resample._amplified(loud, 8.0)
        self.assertEqual(max(amplified), wav.MAX_SAMPLE)
        self.assertEqual(min(amplified), wav.MIN_SAMPLE)

    def test_the_note_records_the_original_peak(self):
        prepared = resample.for_engine(tone(16000, amplitude=554), "wav", "16k_zh")
        self.assertIn("554", " ".join(prepared.notes))


if __name__ == "__main__":
    unittest.main()
