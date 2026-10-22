"""Shared, offline engine capabilities; no model loading or network requests."""
import json
import os
from pathlib import Path

CAPABILITIES = json.loads(Path(__file__).with_name('languages.json').read_text())
LANGUAGES = {code: row['label'] for code, row in CAPABILITIES['languages'].items()}


def supported_languages(tts_engine='qwen', translation_engine='hymt', quality='balanced'):
    speech = CAPABILITIES['tts'].get(tts_engine, {}).get('languages', [])
    if tts_engine == 'qwen':
        # The installed pinned model may expose fewer languages than its family.
        # Read only its small local configuration, never download weights here.
        from .models import REVISIONS
        from .settings import TTS_MODELS
        from huggingface_hub import try_to_load_from_cache
        cache = None
        workspace = os.environ.get('DUBBING_DESKTOP_WORKSPACE')
        if workspace:
            cache = str(Path(workspace)/'Models/hub')
        config = try_to_load_from_cache(TTS_MODELS[quality], 'config.json',
            revision=REVISIONS[TTS_MODELS[quality]], cache_dir=cache)
        if isinstance(config, str):
            ids = json.loads(Path(config).read_text())['talker_config']['codec_language_id']
            speech = [code for code in speech if CAPABILITIES['languages'][code]['qwen'].lower() in ids]
    translation = CAPABILITIES['translation'].get(translation_engine, {}).get('languages', [])
    return {code: LANGUAGES[code] for code in speech if code in translation}


def validate_language(language, tts_engine, translation_engine, quality='balanced'):
    if language not in supported_languages(tts_engine, translation_engine, quality):
        raise ValueError(f'Unsupported target language {language!r} for {tts_engine} with {translation_engine}')


def qwen_language(code):
    return CAPABILITIES['languages'][code]['qwen']


def export_label(code):
    row = CAPABILITIES['languages'][code]
    return row.get('export', row['label'])


def language_matrix():
    from .settings import TTS_MODELS
    return {engine: {quality: {translator: supported_languages(engine, translator, quality)
        for translator in CAPABILITIES['translation']} for quality in TTS_MODELS}
        for engine in CAPABILITIES['tts']}
