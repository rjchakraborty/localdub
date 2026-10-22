"""Real media checks for the bundled voice cleanup plugin."""
import json
import sys

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from pydantic import ValidationError

from dubbing.audio_enhancement import measure
from dubbing.preprocessing import digest, prepare_audio
from dubbing.settings import Options, options_for_job


def fixture_audio(path):
    rng = np.random.default_rng(42)
    t = np.arange(24000 * 4) / 24000
    speech = ((t > 1) & (t < 3)) * (.12 * np.sin(2*np.pi*300*t) + .06*np.sin(2*np.pi*900*t))
    sf.write(path, speech + .015*rng.standard_normal(len(t)) + .04*np.sin(2*np.pi*30*t), 24000, format='WAV')


@pytest.mark.parametrize('strength', ['gentle', 'balanced', 'strong'])
def test_real_cleanup_preserves_timing_and_reduces_noise(tmp_path, strength):
    source, dest = tmp_path/'original.wav', tmp_path/'clean.wav'
    fixture_audio(source)
    original_hash = digest(source)
    receipt = prepare_audio(source, dest, Options(language='es', enhancement_strength=strength))
    raw, _ = sf.read(source)
    cleaned, _ = sf.read(dest)
    gain = 10 ** (receipt['gain_db'] / 20)
    assert len(raw) == len(cleaned)
    assert np.max(np.abs(cleaned)) <= .951
    # Compare a steady noise-only interval, accounting for the reported gain.
    assert np.sqrt(np.mean((cleaned[12000:20000]/gain)**2)) < .7*np.sqrt(np.mean(raw[12000:20000]**2))
    # Speech remains substantially stronger than the cleaned noise floor.
    assert np.sqrt(np.mean(cleaned[30000:60000]**2)) > 2*np.sqrt(np.mean(cleaned[12000:20000]**2))
    assert digest(source) == original_hash
    assert receipt['output_sha256'] == digest(dest)
    assert receipt['before']['frames'] == receipt['after']['frames']
    assert receipt['enabled'] and receipt['version']


def test_disabled_plugin_is_byte_identical_and_does_not_import(tmp_path, monkeypatch):
    source, dest = tmp_path/'original.wav', tmp_path/'clean.wav'
    fixture_audio(source)
    monkeypatch.setitem(sys.modules, 'dubbing.audio_enhancement', None)
    receipt = prepare_audio(source, dest, Options(language='es', audio_enhancement=False))
    assert not receipt['enabled']
    assert source.read_bytes() == dest.read_bytes()
    with pytest.raises(RuntimeError, match='Disable Voice cleanup'):
        prepare_audio(source, dest, Options(language='es'))


def test_legacy_resume_and_validation():
    assert Options(language='es').audio_enhancement
    assert not options_for_job({'options': {'language':'es'}}).audio_enhancement
    assert options_for_job({'options': Options(language='es').model_dump()}).audio_enhancement
    with pytest.raises(ValidationError):
        Options(language='es', enhancement_strength='unknown')


def test_failure_preserves_output_and_cleans_temporary_files(tmp_path):
    source, dest = tmp_path/'original.wav', tmp_path/'clean.wav'
    sf.write(source, np.ones((24000, 2))*.1, 24000)
    dest.write_bytes(b'previous output')
    with pytest.raises(ValueError, match='mono'):
        prepare_audio(source, dest, Options(language='es'))
    assert dest.read_bytes() == b'previous output'
    assert not list(tmp_path.glob('.cleanup-*'))


def test_silence_stays_silent(tmp_path):
    source, dest = tmp_path/'original.wav', tmp_path/'clean.wav'
    sf.write(source, np.zeros(24000), 24000)
    prepare_audio(source, dest, Options(language='es'))
    assert measure(dest)['peak'] == 0


@pytest.mark.parametrize('position', [0, 12000, 23999])
def test_filter_latency_is_compensated_and_final_samples_are_preserved(tmp_path, position):
    source, dest = tmp_path/'original.wav', tmp_path/'clean.wav'
    samples = np.zeros(24000)
    samples[position] = .5
    sf.write(source, samples, 24000)
    prepare_audio(source, dest, Options(language='es'))
    output, _ = sf.read(dest)
    assert len(output) == len(samples)
    assert abs(int(np.argmax(np.abs(output))) - position) <= 1
    assert abs(output[position]) > .01


def test_preferences_persist_disabled_and_strength(tmp_path, monkeypatch):
    monkeypatch.setenv('DUBBING_DESKTOP_WORKSPACE', str(tmp_path))
    monkeypatch.delenv('DUBBING_HOME', raising=False)
    from dubbing.server import app
    client = TestClient(app)
    headers = {'x-dubbing-token': client.get('/api/config').json()['token']}
    values = Options(language='es', audio_enhancement=False, enhancement_strength='strong').model_dump()
    assert client.post('/api/preferences', json=values, headers=headers).status_code == 200
    saved = TestClient(app).get('/api/preferences').json()['options']
    assert not saved['audio_enhancement'] and saved['enhancement_strength'] == 'strong'
    assert json.loads((tmp_path/'Jobs/preferences.json').read_text())['audio_enhancement'] is False


@pytest.mark.parametrize('enabled', [False, True])
def test_real_pipeline_source_stage_and_resume(tmp_path, enabled):
    from dubbing.pipeline import prepare_source
    fixture_audio(tmp_path/'input.audio')
    original_hash = digest(tmp_path/'input.audio')
    job = {'filename': 'recording.wav'}
    options = Options(language='es', audio_enhancement=enabled)
    prepare_source(tmp_path, job, options)
    source = json.loads((tmp_path/'source.json').read_text())
    assert source['sha256'] == original_hash
    assert source['processing_sha256'] == digest(tmp_path/'source.wav')
    assert source['audio_preprocessing']['enabled'] is enabled
    assert source['audio_preprocessing'] == json.loads((tmp_path/'audio-preprocessing.json').read_text())
    assert digest(tmp_path/'input.audio') == original_hash
    before = (tmp_path/'source.wav').stat().st_mtime_ns
    prepare_source(tmp_path, job, options)
    assert (tmp_path/'source.wav').stat().st_mtime_ns == before
