# hermes-tencent-asr

Speech-to-text for [Hermes Agent](https://github.com/NousResearch/hermes-agent)
through Tencent Cloud's **SentenceRecognition**（一句话识别）, registered as the
STT provider `tencent`.

Built for WeChat voice notes specifically: SentenceRecognition accepts **raw
SILK**, which is what WeChat sends, so nothing has to be transcoded first.

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

No dependencies — signing is `hmac`/`hashlib`, the request is `urllib`.

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

## The format problem

`VoiceFormat` is not a hint. Send SILK labelled `ogg-opus` and Tencent does not
error — it returns confident nonsense.

And the filename cannot be trusted. Hermes' unified media cache maps any
extension it does not recognise onto `.ogg`, and `.silk` is not in its table, so
a WeChat voice note lands as `audio_xxxx.ogg` **containing raw SILK**.

So `audio_format.py` sniffs the leading bytes first and falls back to the
extension only when nothing matches. When neither identifies a format Tencent
accepts, the provider **refuses** rather than guessing — an error you can read
beats a transcript that is quietly wrong.

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
└── settings.py          credentials, region, engine
tests/                   stdlib unittest; no network, no Hermes
```

## Tests

```bash
python3 -m unittest discover -s tests -t tests
```

46 tests, no dependencies — the Hermes runtime is stubbed in
`tests/_hermes_stubs.py`.

What they pin is the *shape* of the signature and the provider's contract
(never raises, refuses unknown formats, returns the right envelope). They do
**not** prove the signature is one Tencent accepts — only a live call does
that.

## Status

Not yet verified against the live Tencent API. The signing is a port of a
working TypeScript implementation (OpenClaw `src/audio.ts`), but the first real
transcription is what confirms it.
