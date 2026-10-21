# LocalDub

By [Raja Chakraborty](https://github.com/rjchakraborty) · [Portfolio](https://rjchakraborty.github.io/)

Local audio dubbing for Apple Silicon. Turn English recordings into Mandarin
Chinese or Spanish using on-device speech recognition, translation and reference
voice synthesis. Review the transcript, repair individual passages and export
audio with captions.

**Status: pre-release, under product validation. No production release is available yet.**
The application aims to retain phrasing, pauses and vocal character. It does not
guarantee identical voice, emotion or meaning; listen to the result before sharing.

## What it does

- Local files and direct HTTP(S) audio links, including public or signed S3/GCS links.
- Batches of up to 20 inputs, processed sequentially to limit memory pressure.
- Mandarin and Spanish output, configurable pacing, pauses and reference voice.
- Cancel/resume, cached completed stages, transcript/translation corrections and
  selective speech regeneration.
- MP3, WAV, WebVTT captions and machine-readable review reports in named,
  versioned export folders.
- Optional public Podbean episode resolver; separately installed source plugins.
- Native Mac window with automatic private Python, package and model setup.

## Requirements

Apple Silicon, macOS 26 or later, and at least 25 GB free for initial setup.
Development validation uses a 24 GB M4 Mac mini. Lower-memory Macs, Intel Macs,
Windows and Linux inference are not certified. Initial default model downloads
are approximately 7.84 GB, plus Python and packages. Network access is needed for
setup and URL inputs; audio inference runs locally. Optional models download
separately when selected.

## Run from source

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
  B --> C[Whisper transcript]
  C --> D[Complete-thought translation]
  D --> E[Reference voice synthesis]
  E --> F[Pause-aware assembly]
  F --> G[Independent speech readback]
  G --> H[Review and export]
```

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
voices you have permission to process. Project repository, release and issue links
will be added when the personal GitHub destination is confirmed.
