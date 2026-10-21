"""Reviewed model snapshots; never execute remote model code."""
import os
from pathlib import Path
from huggingface_hub import snapshot_download

from .settings import ASR_MODEL, TRANSLATION_MODEL, TTS_MODELS, INDEXTTS_MODEL, INDEXTTS_REVISION

REVISIONS = {
    INDEXTTS_MODEL: INDEXTTS_REVISION,
    "mlx-community/Hy-MT2-7B-4bit": "9b7204bdb161490a8ce49ce607c1310cc3fd03ad",
    ASR_MODEL: "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb",
    TRANSLATION_MODEL: "50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b",
    TTS_MODELS["balanced"]: "50f45ef0047cde7e84c2ef04326acb8ada2436a7",
    TTS_MODELS["quality"]: "e7dd0585652209fa0d7783659aad4e8a324de11c",
    "Helsinki-NLP/opus-mt-en-es": "5bc4493d463cf000c1f0b50f8d56886a392ed4ab",
    "Helsinki-NLP/opus-mt-en-zh": "408d9bc410a388e1d9aef112a2daba955b945255",
    "Nextcloud-AI/madlad400-3b-mt-ct2-int8": "aa32bbdeba7880eff2096ec044cb155a340a9400",
}


def model_path(name):
    patterns = ["*.json", "*.safetensors", "*.npz", "*.tiktoken", "*.txt", "*.model", "*.jinja", "LICENSE*", "README.md"]
    if name.startswith("Helsinki-NLP/"):
        patterns += ["pytorch_model.bin", "*.spm"]
    if name.startswith("Nextcloud-AI/"):
        patterns += ["model.bin"]
    offline_ready=False
    desktop=os.environ.get('DUBBING_DESKTOP_WORKSPACE')
    if desktop:
        from .desktop.bootstrap import DEFAULT_MODELS, installed
        workspace=Path(desktop).resolve()
        offline_ready=name in DEFAULT_MODELS and installed(workspace/'Runtime/models-ready.json',workspace/'Models/hub')
    return snapshot_download(name, revision=REVISIONS[name], allow_patterns=patterns,local_files_only=offline_ready)


if __name__ == "__main__":
    import json
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        names = [ASR_MODEL, "mlx-community/Hy-MT2-7B-4bit", TTS_MODELS["balanced"]]
        for name, path in zip(names, pool.map(model_path, names)):
            print(json.dumps({"model": name, "revision": REVISIONS[name], "path": path}), flush=True)
