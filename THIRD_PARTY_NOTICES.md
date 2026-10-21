# Third-party software and models

The MIT license covers this application's original code, not all dependencies,
models or user recordings. Model weights are downloaded separately; they are
not committed to the repository or included in the installer.

| Component | Upstream | License / notes |
| --- | --- | --- |
| Whisper | https://github.com/openai/whisper | MIT; MLX conversion pinned in source |
| Hy-MT2 7B | https://huggingface.co/tencent/Hy-MT2-7B | Apache 2.0; MLX conversion pinned in source |
| Qwen3-TTS | https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base | Apache 2.0; 0.6B default |
| MLX Audio | https://github.com/Blaizzy/mlx-audio | MIT; installed package retains its license |
| MLX LM | https://github.com/ml-explore/mlx-lm | MIT |
| FFmpeg | https://ffmpeg.org/legal.html | LGPL build, separate executable; corresponding source included in app |
| LAME | https://lame.sourceforge.io/ | LGPL; static library inside standalone FFmpeg tool; source included |
| uv | https://github.com/astral-sh/uv | MIT or Apache 2.0; licenses included in app |

Optional translation and IndexTTS models have separate upstream terms. Inspect
their pinned model cards and license files before use or redistribution. The
experimental IndexTTS path is not part of the default installed model set.
Dependency versions are recorded in `dubbing/requirements-tested.txt`; installed
distributions retain their notices. The build includes upstream media source
archives and the exact build script so recipients can rebuild those tools.
