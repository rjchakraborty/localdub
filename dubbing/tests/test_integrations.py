import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from dubbing import integrations
from dubbing.privacy import public_metadata


@pytest.fixture
def config(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALDUB_CONFIG',str(tmp_path/'integrations.json'))
    return tmp_path/'integrations.json'


def test_optional_integrations_are_disabled_by_default(config):
    assert integrations.load().model_dump()=={'podbean':False,'plugins':[]}


def test_toggle_keeps_private_plugin_configuration(config):
    config.write_text(json.dumps({'plugins':['private-example']}))
    integrations.set_podbean(True)
    assert integrations.load().plugins==['private-example']
    assert config.stat().st_mode & 0o777 == 0o600


def test_disabled_plugins_are_never_loaded(config,monkeypatch,tmp_path):
    class Entry:
        name='private-example'
        def load(self):raise AssertionError('Disabled code executed')
    monkeypatch.setattr(integrations,'entry_points',lambda **kw:[Entry()])
    assert integrations.resolve_metadata('https://example.com/audio.mp3',tmp_path) is None


def test_missing_explicit_plugin_fails_clearly(config,monkeypatch,tmp_path):
    config.write_text(json.dumps({'plugins':['missing']}))
    monkeypatch.setattr(integrations,'entry_points',lambda **kw:[])
    with pytest.raises(ValueError,match='missing or ambiguous'):
        integrations.resolve_metadata('https://example.com/audio.mp3',tmp_path)


def test_integration_settings_require_same_origin_token(config,tmp_path,monkeypatch):
    monkeypatch.setenv('DUBBING_DESKTOP_WORKSPACE',str(tmp_path))
    monkeypatch.delenv('DUBBING_HOME',raising=False)
    from dubbing.server import app
    client=TestClient(app)
    assert client.post('/api/integrations',json={'podbean':True}).status_code==403
    token=client.get('/api/config').json()['token']
    assert client.post('/api/integrations',json={'podbean':True},headers={'x-dubbing-token':token}).status_code==200
    assert client.get('/api/integrations').json()['podbean'] is True


def test_signed_urls_and_userinfo_never_leave_in_portable_metadata():
    private={'source':'https://user:password@storage.example/a.wav?X-Amz-Signature=secret#token',
             'nested':['https://storage.example/b.mp3?X-Goog-Credential=private']}
    safe=public_metadata(private)
    assert safe=={'source':'https://storage.example/a.wav','nested':['https://storage.example/b.mp3']}
    assert 'secret' in private['source']
