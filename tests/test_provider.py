"""The provider's contract with Hermes.

Two rules from ``agent/transcription_provider.py`` matter more than the happy
path, because breaking either takes down something bigger than one clip:

* ``transcribe`` must NOT raise — a failure becomes the error envelope;
* ``is_available`` must NOT raise and must NOT touch the network.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _loader import load  # noqa: E402
import _hermes_stubs as stubs  # noqa: E402

load()
stubs.install()

from tencent_asr import client as client_mod  # noqa: E402
from tencent_asr.client import AsrError, AsrResult  # noqa: E402
from tencent_asr.provider import TencentASRProvider  # noqa: E402

SILK = b"#!SILK_V3" + b"\x00" * 64


def write(tmpdir, name, data=SILK):
    path = Path(tmpdir) / name
    path.write_bytes(data)
    return str(path)


class Identity(unittest.TestCase):
    def setUp(self):
        stubs.clear_env()

    def test_name_is_not_a_builtin(self):
        # Hermes rejects a provider whose name collides with a built-in.
        self.assertNotIn(
            TencentASRProvider().name, {"local", "local_command", "groq", "openai"}
        )

    def test_name_matches_the_stt_provider_key(self):
        self.assertEqual(TencentASRProvider().name, "tencent")

    def test_display_name(self):
        self.assertEqual(TencentASRProvider().display_name, "Tencent Cloud ASR")

    def test_catalog_is_not_empty_and_has_a_default(self):
        provider = TencentASRProvider()
        self.assertTrue(provider.list_models())
        self.assertEqual(provider.default_model(), "16k_zh")


class Availability(unittest.TestCase):
    def setUp(self):
        stubs.clear_env()
        self.addCleanup(stubs.clear_env)

    def test_unavailable_without_credentials(self):
        self.assertFalse(TencentASRProvider().is_available())

    def test_available_with_both(self):
        stubs.set_env(TENCENT_ASR_SECRET_ID="AKID", TENCENT_ASR_SECRET_KEY="key")
        self.assertTrue(TencentASRProvider().is_available())

    def test_one_credential_is_not_enough(self):
        stubs.set_env(TENCENT_ASR_SECRET_ID="AKID")
        self.assertFalse(TencentASRProvider().is_available())

    def test_never_raises(self):
        # Hermes calls this on every repaint of the picker.
        stubs.set_env(TENCENT_ASR_SECRET_ID="\x00bad")
        try:
            TencentASRProvider().is_available()
        except Exception as exc:  # pragma: no cover
            self.fail("is_available raised: %r" % exc)


class Transcribe(unittest.TestCase):
    def setUp(self):
        stubs.clear_env()
        stubs.set_env(TENCENT_ASR_SECRET_ID="AKID", TENCENT_ASR_SECRET_KEY="key")
        self.addCleanup(stubs.clear_env)
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self._real_call = client_mod.transcribe
        self.addCleanup(lambda: setattr(client_mod, "transcribe", self._real_call))
        # provider.py imported the symbol directly, so patch it there too.
        import tencent_asr.provider as provider_mod

        self._provider_mod = provider_mod
        self._real_provider_call = provider_mod.call_tencent
        self.addCleanup(
            lambda: setattr(provider_mod, "call_tencent", self._real_provider_call)
        )

    def _stub_call(self, fn):
        self._provider_mod.call_tencent = fn

    def test_happy_path(self):
        seen = {}

        def fake(audio, voice_format, **kwargs):
            seen["format"] = voice_format
            seen["engine"] = kwargs.get("engine")
            return AsrResult(transcript="你好世界", duration_ms=1200, request_id="req-1")

        self._stub_call(fake)
        result = TencentASRProvider().transcribe(write(self._dir.name, "voice.silk"))

        self.assertTrue(result["success"])
        self.assertEqual(result["transcript"], "你好世界")
        self.assertEqual(result["provider"], "tencent")
        self.assertEqual(seen["format"], "silk")

    def test_a_lying_extension_still_sends_silk(self):
        # Hermes names it .ogg; the bytes are SILK. This is the real case.
        seen = {}

        def fake(audio, voice_format, **kwargs):
            seen["format"] = voice_format
            return AsrResult(transcript="ok")

        self._stub_call(fake)
        TencentASRProvider().transcribe(write(self._dir.name, "audio_abc.ogg"))
        self.assertEqual(seen["format"], "silk")

    def test_model_argument_overrides_the_engine(self):
        seen = {}

        def fake(audio, voice_format, **kwargs):
            seen["engine"] = kwargs.get("engine")
            return AsrResult(transcript="ok")

        self._stub_call(fake)
        TencentASRProvider().transcribe(write(self._dir.name, "v.silk"), model="16k_en")
        self.assertEqual(seen["engine"], "16k_en")

    def test_missing_credentials_is_an_envelope_not_a_raise(self):
        stubs.clear_env()
        result = TencentASRProvider().transcribe(write(self._dir.name, "v.silk"))
        self.assertFalse(result["success"])
        self.assertIn("SECRET_ID", result["error"])
        self.assertEqual(result["transcript"], "")

    def test_missing_file_is_an_envelope(self):
        result = TencentASRProvider().transcribe("/nonexistent/clip.silk")
        self.assertFalse(result["success"])
        self.assertEqual(result["transcript"], "")

    def test_unknown_format_refuses_rather_than_guesses(self):
        path = write(self._dir.name, "mystery.bin", b"\x01\x02\x03\x04" * 16)
        called = []
        self._stub_call(lambda *a, **k: called.append(1) or AsrResult(transcript="x"))
        result = TencentASRProvider().transcribe(path)
        self.assertFalse(result["success"])
        self.assertEqual(called, [], "must not call Tencent with a guessed format")

    def test_api_error_becomes_an_envelope_with_the_request_id(self):
        def fake(*a, **k):
            raise AsrError("AuthFailure: bad key", code="AuthFailure", request_id="req-9")

        self._stub_call(fake)
        result = TencentASRProvider().transcribe(write(self._dir.name, "v.silk"))
        self.assertFalse(result["success"])
        self.assertIn("AuthFailure", result["error"])
        self.assertIn("req-9", result["error"])

    def test_an_unexpected_exception_still_does_not_raise(self):
        def boom(*a, **k):
            raise ZeroDivisionError("something silly")

        self._stub_call(boom)
        result = TencentASRProvider().transcribe(write(self._dir.name, "v.silk"))
        self.assertFalse(result["success"])
        self.assertIn("unexpected", result["error"])

    def test_unknown_extra_kwargs_are_ignored(self):
        self._stub_call(lambda *a, **k: AsrResult(transcript="ok"))
        result = TencentASRProvider().transcribe(
            write(self._dir.name, "v.silk"), language="zh-CN", prompt="词汇表", nonsense=1
        )
        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
