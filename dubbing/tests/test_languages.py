import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from dubbing import batches
from dubbing.languages import CAPABILITIES, export_label, qwen_language, supported_languages
from dubbing.pipeline import read, save, translate
from dubbing.settings import Options, home


@pytest.mark.parametrize('engine', CAPABILITIES['tts'])
def test_all_declared_targets_validate_and_batch(engine, monkeypatch):
    monkeypatch.setattr(batches, 'public_url', lambda source: source)
    languages = supported_languages(engine)
    for language in languages:
        assert Options(language=language, tts_engine=engine).language == language
        assert export_label(language)
        if engine == 'qwen': assert qwen_language(language)
    request = batches.BatchRequest(request_id=uuid4(), sources=['https://example.com/audio.mp3'],
        languages=list(languages), options=Options(language=next(iter(languages)), tts_engine=engine))
    result = batches.create(request)
    assert result['total'] == len(languages)
    assert batches.create(request) == result
    assert {read(home()/'jobs'/job/'job.json')['options']['language'] for job in result['jobs']} == set(languages)


def test_unsupported_engine_pair_rejected_before_any_batch_files(monkeypatch):
    monkeypatch.setattr(batches, 'public_url', lambda source: source)
    for engine, language in [('qwen', 'ar'), ('indextts25', 'fr')]:
        with pytest.raises(ValueError, match='Unsupported'):
            Options(language=language, tts_engine=engine)
    with pytest.raises(ValueError, match='Unsupported'):
        batches.create(batches.BatchRequest(request_id=uuid4(), sources=['https://example.com/audio.mp3'],
            languages=['zh', 'fr'], options=Options(language='zh', translation_engine='opus')))
    assert not (home()/'jobs').exists()


def test_installed_model_language_metadata_limits_capabilities(tmp_path, monkeypatch):
    import huggingface_hub
    config = tmp_path/'config.json'
    config.write_text(json.dumps({'talker_config': {'codec_language_id': {'french': 1, 'spanish': 2}}}))
    monkeypatch.setattr(huggingface_hub, 'try_to_load_from_cache', lambda *args, **kwargs: str(config))
    assert set(supported_languages()) == {'fr', 'es'}
    with pytest.raises(ValueError, match='Unsupported'): Options(language='zh')
    assert Options(language='fr').language == 'fr'


def test_config_is_same_capability_source_as_validation():
    from dubbing.server import app
    config = TestClient(app).get('/api/config').json()
    for engine, profiles in config['language_matrix'].items():
        for quality, translators in profiles.items():
            for translator, languages in translators.items():
                assert languages == supported_languages(engine, translator, quality)
                for code in languages:
                    Options(language=code, tts_engine=engine, quality=quality, translation_engine=translator)


def test_same_language_retains_original_text_without_loading_translation_model(tmp_path):
    transcript = {'language': 'en', 'text': 'It is our story.',
        'segments': [{'id': 0, 'start': 0, 'end': 3, 'text': 'It is our story.'}]}
    save(tmp_path/'transcript.json', transcript)
    translate(tmp_path, Options(language='en', semantic_translation=False))
    row = read(tmp_path/'translation.json')[0]
    assert row['translation'] == transcript['text']
    assert row['translation_model'] == 'source_passthrough'


def test_export_labels_preserve_existing_folders_and_support_new_targets():
    assert export_label('zh') == 'Mandarin'
    assert export_label('es') == 'Spanish'
    assert export_label('ja') == 'Japanese'
    assert export_label('ar') == 'Arabic'
