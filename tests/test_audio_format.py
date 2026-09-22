"""Format detection.

The filename cannot be trusted. Hermes' unified media cache maps any extension
it does not know onto ``.ogg``, and ``.silk`` is not in its table — so a WeChat
voice note arrives as ``audio_xxxx.ogg`` containing raw SILK. Sending that to
Tencent as ``ogg-opus`` does not error; it returns confident nonsense.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _loader import load  # noqa: E402

load()

from tencent_asr.audio_format import (  # noqa: E402
    SUPPORTED_FORMATS,
    describe,
    format_for,
    sniff_format,
)

SILK = b"#!SILK_V3" + b"\x00" * 32
SILK_PREFIXED = b"\x02#!SILK_V3" + b"\x00" * 32  # some clients prepend a byte
WAV = b"RIFF\x24\x08\x00\x00WAVEfmt "
OGG = b"OggS\x00\x02\x00\x00" + b"\x00" * 24
MP3_ID3 = b"ID3\x03\x00\x00\x00" + b"\x00" * 24
MP3_SYNC = b"\xff\xfb\x90\x00" + b"\x00" * 24
M4A = b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 16
AMR = b"#!AMR\n" + b"\x00" * 24


class Sniffing(unittest.TestCase):
    def test_silk(self):
        self.assertEqual(sniff_format(SILK), "silk")

    def test_silk_with_a_leading_byte(self):
        self.assertEqual(sniff_format(SILK_PREFIXED), "silk")

    def test_wav(self):
        self.assertEqual(sniff_format(WAV), "wav")

    def test_ogg(self):
        self.assertEqual(sniff_format(OGG), "ogg-opus")

    def test_mp3_with_id3(self):
        self.assertEqual(sniff_format(MP3_ID3), "mp3")

    def test_bare_mpeg_frame(self):
        self.assertEqual(sniff_format(MP3_SYNC), "mp3")

    def test_m4a(self):
        self.assertEqual(sniff_format(M4A), "m4a")

    def test_amr(self):
        self.assertEqual(sniff_format(AMR), "amr")

    def test_unknown(self):
        self.assertIsNone(sniff_format(b"not audio at all"))

    def test_empty(self):
        self.assertIsNone(sniff_format(b""))


class FormatFor(unittest.TestCase):
    def test_bytes_beat_a_lying_extension(self):
        # The case this module exists for.
        self.assertEqual(format_for("/cache/audio/audio_abc.ogg", SILK), "silk")

    def test_extension_is_used_when_bytes_say_nothing(self):
        self.assertEqual(format_for("/tmp/clip.wav", b"\x00" * 32), "wav")

    def test_opus_extension_maps_to_tencents_name(self):
        self.assertEqual(format_for("/tmp/clip.opus", b"\x00" * 32), "ogg-opus")

    def test_silk_extension_still_works(self):
        self.assertEqual(format_for("/tmp/voice.silk", b"\x00" * 32), "silk")

    def test_unknown_everything_is_none(self):
        # None means "refuse", not "guess" — a wrong VoiceFormat is worse than
        # an error the user can read.
        self.assertIsNone(format_for("/tmp/mystery.bin", b"\x00" * 32))

    def test_every_mapped_format_is_one_tencent_accepts(self):
        for path, data in (("a.wav", WAV), ("a.ogg", OGG), ("a.silk", SILK), ("a.amr", AMR)):
            self.assertIn(format_for("/tmp/" + path, data), SUPPORTED_FORMATS)


class Describe(unittest.TestCase):
    def test_reports_both_what_the_name_said_and_what_the_bytes_say(self):
        text = describe("/cache/audio_abc.ogg", SILK)
        self.assertIn(".ogg", text)
        self.assertIn("silk", text)

    def test_handles_no_extension(self):
        self.assertIn("<no extension>", describe("/tmp/blob", b""))


if __name__ == "__main__":
    unittest.main()
