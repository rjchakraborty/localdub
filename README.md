# LocalDub

By [Raja Chakraborty](https://github.com/rjchakraborty) · [Portfolio](https://rjchakraborty.github.io/)

Local audio dubbing for Apple Silicon. Turn recordings into the languages supported
by the selected engine using on-device speech recognition, translation and reference
voice synthesis. Review the transcript, repair individual passages and export
audio with captions.

**Status: preview.** [Download the Mac app](https://github.com/rjchakraborty/localdub/releases).
The 0.3.3 Mac release is Developer ID signed and Apple notarized. Human listening
acceptance remains pending; check each release's signing and validation records.
The application aims to retain phrasing, pauses and vocal character. It does not
guarantee identical voice, emotion or meaning; listen to the result before sharing.

## What it does

- Local files and direct HTTP(S) audio links, including public or signed S3/GCS links.
- Up to 20 uploaded files or 200 URLs per batch, processed sequentially to limit memory pressure.
- Engine-driven language selection, configurable pacing, pauses and reference voice.
- Cancel/resume, cached completed stages, transcript/translation corrections and
  selective speech regeneration.
- MP3, WAV, WebVTT captions and machine-readable review reports in named,
  versioned export folders.
- Optional public Podbean episode resolver; separately installed source plugins.
- Persistent multilingual URL batches, sequential processing, pause/retry and organized local exports.
- Optional private catalogue plugins: import up to 10,000 episode metadata records, choose a language, then download, dub and export one episode at a time. See [integration setup](docs/INTEGRATIONS.md).
- Native Mac window, Finder/Dock icon, and automatic private Python, package and model setup.

### Output languages

The selector and URL batch language list come from the backend capability matrix.
Qwen3-TTS supports Mandarin Chinese, English, Japanese, Korean, German, French,
Russian, Portuguese, Spanish and Italian. The optional IndexTTS 2.5 adapter supports
Mandarin Chinese, English, Japanese, Spanish and Arabic when installed separately.
Only languages shared by the speech and translation engines are offered. Existing
OPUS snapshots support Mandarin and Spanish; the default Hy-MT2 supports all the
speech targets above. Same-language audio keeps the source transcript without
paraphrasing it through translation.

`dubbing/languages.json` records reviewed engine capabilities and upstream sources.
The installed Qwen model's language-token metadata further limits its options.
No model is loaded or downloaded just to populate the selector. API validation,
translation prompts, rendering and export names use the same capability source;
engine upgrades require reviewing that metadata. Model support does not establish
listening quality in every language.

## Requirements

Apple Silicon, macOS 26 or later, and at least 25 GB free for initial setup.
Development validation uses a 24 GB M4 Mac mini. Lower-memory Macs, Intel Macs,
Windows and Linux inference are not certified. Initial default model downloads
are approximately 7.84 GB, plus Python and packages. Network access is needed for
setup and URL inputs; audio inference runs locally. Optional models download
separately when selected.

## Run from source

For the packaged app, download the versioned `LocalDub-…-arm64.zip` from the
[release page](https://github.com/rjchakraborty/localdub/releases),
check it against `SHA256SUMS`, extract it and copy `LocalDub.app` to Applications.
Choose a workspace on first launch and let setup download Python, packages and
models. Setup progress appears in the native window. An external SSD is optional.
The 0.3.3 distribution includes a stapled Apple notarization ticket. Older previews
and unsigned source builds have different signing status. Do not disable Gatekeeper
to run a blocked or unverifiable package. Building from source remains available below.

Install Python 3.11 and FFmpeg/ffprobe, then from this checkout:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r dubbing/requirements-tested.txt
export DUBBING_HOME="$HOME/Library/Application Support/LocalDub/Jobs"
export HF_HOME="$HOME/Library/Application Support/LocalDub/Models"
.venv/bin/python -m uvicorn dubbing.server:app --host 127.0.0.1 --port 8092 --no-access-log
```

Open <http://127.0.0.1:8092>. Add a file or direct audio URL, select a language,
then start. The first source run downloads the required models. The native app
adds setup progress and a storage picker; see [building the Mac app](docs/RELEASING.md).

Inputs are bounded to 512 MiB and two hours. Common WAV, MP3, M4A/AAC, FLAC and
Ogg audio are covered by media tests. Arbitrary websites, streaming playlists,
DRM content and every possible codec are not supported.

## Sources and privacy

Optional integrations are configured locally; [integration guide](docs/INTEGRATIONS.md).
The core needs no organization account, database, API key or cloud subscription.
Public Podbean episodes need no API key. Private cloud access uses a short-lived
signed HTTPS URL created in your own account; native bucket browsing is not yet
implemented.

Job inputs, transcripts and source URLs are stored on your machine. Signed URLs
are credentials: their query strings remain in private job state so retries can
work, but URL query strings and user information are removed from exported JSON
metadata. Review reports and recordings before sharing. No analytics or automatic
audio upload is included. See [security and privacy](SECURITY.md).

## How it works

```mermaid
flowchart LR
  A[File or audio URL] --> B[Validate and decode]
  B --> P[Optional bundled voice cleanup]
  P --> C[Whisper transcript]
  C --> D[Complete-thought translation]
  D --> E[Reference voice synthesis]
  E --> F[Pause-aware assembly]
  F --> G[Independent speech readback]
  G --> H[Review and export]
```

Voice cleanup ships with the app and source and is enabled for new jobs. Disable
it under **Bundled audio plugin**, or choose Gentle (default), Balanced or Strong.
The choice is saved for future jobs and frozen per queued job. Existing jobs keep
their original processing when resumed. The plugin reduces steady noise and
low-frequency rumble, then adjusts level with at most 6 dB gain and peak headroom.
It preserves duration and pauses; input recordings are never overwritten.
`source-original.wav` retains the decoded input, `source.wav` feeds recognition
and voice references, and `audio-preprocessing.json` records settings, hashes and
signal measurements. Processed audio uses a separate transcript cache identity.
The plugin is isolated in `dubbing/audio_enhancement.py` behind a lazy loader;
disabled jobs work without it. No cloud service or extra model is required.

Filtering can change voice texture, particularly at Strong. It cannot remove all
noise, separate speakers/music, reverse clipping or guarantee better transcripts.
Compare original and processed audio and review the transcript on difficult input.
Implementation uses FFmpeg's [noise reduction and high-pass filters](https://ffmpeg.org/ffmpeg-filters.html#afftdn).

The default uses Whisper large-v3-turbo, Hy-MT2 7B and Qwen3-TTS 0.6B through
MLX. Models use immutable revisions recorded in `dubbing/models.py`; remote model
code is not executed. Model and software licenses remain separate; see
[third-party notices](THIRD_PARTY_NOTICES.md).

IndexTTS 2.5 is an experimental optional path with its own runtime requirements.
It is not installed by the default app. Automated transcription similarity can
miss mistranslations, wrong numbers and voice changes. Spanish numeric checks
are implemented; Mandarin number semantics and bilingual listening quality are
not automatically certified. Multi-speaker diarization and perfect lip sync are
not implemented. See [validation](docs/VALIDATION.md).

## Development

```sh
python3.11 -m pip install -r requirements-test.txt
python3.11 -m pytest -p no:cacheprovider dubbing/tests
python3.11 scripts/check_public_tree.py
```

Tests exercise real audio decoding/assembly and API controls without downloading
models. Real inference and native first-launch checks are separate acceptance
steps. [Contributing](CONTRIBUTING.md) · [release process](docs/RELEASING.md).

Application source is [MIT licensed](LICENSE). Use recordings and reference
voices you have permission to process. [Repository](https://github.com/rjchakraborty/localdub)
· [Issues](https://github.com/rjchakraborty/localdub/issues)
· [Release validation](docs/VALIDATION.md).
