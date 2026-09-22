# hermes-tencent-asr

Speech-to-text for [Hermes Agent](https://github.com/NousResearch/hermes-agent)
through Tencent Cloud's **SentenceRecognition**（一句话识别）, registered as the
STT provider `tencent`.

Built for WeChat voice notes specifically — and most of what is in here exists
because that path has two traps in it, both of which fail *silently*.

---

## Why a provider plugin and not a patch

Hermes has a first-class extension point for this —
`ctx.register_transcription_provider()` — and an explicit policy against the
alternative:

> **Plugins never touch core.** A plugin MUST NOT modify `run_agent.py`,
> `cli.py`, `gateway/run.py`… If it needs a capability the framework lacks,
> widen the **generic** plugin surface — never hardcode plugin-specific logic
> into core. — `plugins/AGENTS.md`

There is a practical reason too: `hermes update` runs `git fetch` +
`merge --ff-only` inside `/usr/local/lib/hermes-agent`, so a core patch has to
be re-applied after every upgrade. Everything under `~/.hermes/` is untouched
by that.

The other tempting place is the WeChat channel plugin, since it already has the
audio bytes. That is what the OpenClaw version did — but only because OpenClaw
had no central STT layer. Here it would mean transcription works for WeChat and
nowhere else, with its own private config, while Hermes' own `transcribe_audio`
tool still fails.

## Install

```bash
git clone <this repo> ~/.hermes/plugins/tencent-asr
hermes plugins enable tencent-asr
```

No dependencies — signing is `hmac`/`hashlib`, the request is `urllib`, and the
resampler is `wave` plus `array`.

## Configure

```bash
# ~/.hermes/.env    访问管理 → API 密钥管理
TENCENT_ASR_SECRET_ID=AKID...
TENCENT_ASR_SECRET_KEY=...
```

```yaml
# ~/.hermes/config.yaml
stt:
  provider: tencent
```

Optional: `TENCENT_ASR_REGION` (default `ap-shanghai`) and
`TENCENT_ASR_ENGINE` (default `16k_zh`; also `16k_zh_dialect`, `16k_en`,
`16k_yue` — some need enabling on the account first).

Credentials are read through Hermes' profile-scoped secret store, never
`os.environ` directly: one gateway can serve several profiles, and a raw env
read would hand one profile's key to another.

## Limits

SentenceRecognition is for **short clips**:

| | |
|---|---|
| Duration | 60 seconds |
| Size | 3 MB (inline base64) |
| Free tier | 5,000 requests/month |

Anything longer needs Tencent's 录音文件识别 (RecordTask), which is a different
API with an async callback — not implemented here.

## Trap 1: the format is not what the filename says

`VoiceFormat` is not a hint. Send SILK labelled `ogg-opus` and Tencent does not
error — it returns confident nonsense.

And the filename cannot be trusted. Hermes' unified media cache maps any
extension it does not recognise onto `.ogg`, and `.silk` is not in its table, so
a WeChat voice note lands as `audio_xxxx.ogg` **containing raw SILK**.

So `audio_format.py` sniffs the leading bytes first and falls back to the
extension only when nothing matches. When neither identifies a format Tencent
accepts, the provider **refuses** rather than guessing — an error you can read
beats a transcript that is quietly wrong.

## Trap 2: the engine name is a promise about the sample rate

`16k_zh` does not *describe* the audio. It tells SentenceRecognition to read the
samples at 16 kHz. Feed it anything else and Tencent walks the buffer at the
wrong speed, then returns HTTP 200, a plausible `AudioDuration`, and an empty
`Result`.

SentenceRecognition does accept raw SILK — but the provider never sees it.
Hermes decodes `.silk` to WAV **before** provider dispatch
(`tools/transcription_audio.py`), and it does so like this:

```python
pilk.silk_to_wav(file_path, converted_path)   # no rate argument
```

```python
def silk_to_wav(silk: str, wav: str, rate: int = 24000):   # pilk's default
```

So every WeChat voice note reaches this plugin at **24 kHz** — a rate no Tencent
engine accepts. Measured on two real clips:

```
                     as Hermes sends it        after resample.py
audio_2eefa24c9d86   24000Hz peak 671     ->   16000Hz peak 13420
  Tencent            5159ms -> ''         ->   5160ms -> '测试测试一二三。'
audio_37f29f7e35bc   24000Hz peak 556     ->   16000Hz peak 11100
  Tencent            4499ms -> '测试一下。' ->   4500ms -> '你好你好你好。测试一下。'
```

`resample.py` therefore rewrites WAV input to whatever rate the engine's prefix
promises (`16k_*` → 16000, `8k_*` → 8000), and leaves an unrecognised prefix
alone rather than guessing. Downsampling averages each output sample's window
instead of decimating, because plain decimation folds 8–12 kHz back onto
4–8 kHz, which is where fricatives live.

The same pass lifts a faint recording: WeChat notes have arrived at ~-35 dBFS,
quiet enough to cost words. Gain is applied only below a quarter of full scale,
capped at 20×, and always logged with the original peak — a silent adjustment
is the thing this plugin exists to avoid.

Formats other than WAV pass through byte-for-byte: their rate lives inside a
container this plugin does not parse, and a wrong guess is worse than none.

## Layout

```
plugin.yaml              manifest; env declarations drive the setup UI
__init__.py              re-exports register()
tencent_asr/
├── plugin.py            register(ctx) — the only thing Hermes calls
├── provider.py          TencentASRProvider(TranscriptionProvider)
├── client.py            one SentenceRecognition call
├── signing.py           TC3-HMAC-SHA256
├── audio_format.py      bytes/extension -> VoiceFormat
├── resample.py          match the engine's rate; lift a faint recording
├── wav.py               16-bit PCM WAV in and out
└── settings.py          credentials, region, engine
tests/                   stdlib unittest; no network, no Hermes
```

## Tests

```bash
python3 -m unittest discover -s tests -t tests
```

70 tests, no dependencies — the Hermes runtime is stubbed in
`tests/_hermes_stubs.py`.

What they pin is the *shape* of the signature, the provider's contract (never
raises, refuses unknown formats, returns the right envelope) and the resampler's
behaviour end to end. They do **not** prove the signature is one Tencent
accepts — only a live call does that.

## Status

Verified against the live API on 2026-09-22: signing, format detection and
resampling, on real WeChat voice notes (the two transcripts above).
