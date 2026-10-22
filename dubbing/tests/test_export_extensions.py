from types import SimpleNamespace

import pytest

from dubbing import integrations


def test_only_enabled_export_extensions_run(tmp_path,monkeypatch):
    monkeypatch.setenv('DUBBING_DESKTOP_WORKSPACE',str(tmp_path))
    monkeypatch.delenv('DUBBING_HOME',raising=False)
    monkeypatch.setattr(integrations,'load',lambda:SimpleNamespace(plugins=[]))
    entry=SimpleNamespace(name='example',load=lambda:(_ for _ in ()).throw(AssertionError('Disabled code executed')))
    monkeypatch.setattr(integrations,'entry_points',lambda **kwargs:[entry])
    assert integrations.export_extensions(tmp_path,{})==[]


def test_hook_receives_immutable_receipt_and_errors_are_redacted(tmp_path,monkeypatch):
    monkeypatch.setenv('DUBBING_DESKTOP_WORKSPACE',str(tmp_path))
    monkeypatch.delenv('DUBBING_HOME',raising=False)
    monkeypatch.setattr(integrations,'load',lambda:SimpleNamespace(plugins=['example']))
    receipt={'folder':str(tmp_path/'Exports'),'files':{'audio.mp3':'verified'}}
    def hook(folder,received,config):
        assert received is receipt and config==tmp_path/'Plugins/example'
        return {'manifest':'example/tracks.json'}
    monkeypatch.setattr(integrations,'entry_points',lambda **kwargs:[SimpleNamespace(name='example',load=lambda:hook)])
    assert integrations.export_extensions(tmp_path,receipt)[0]['result']['manifest']=='example/tracks.json'
    def fail(*args):raise ValueError('password=SECRET')
    monkeypatch.setattr(integrations,'entry_points',lambda **kwargs:[SimpleNamespace(name='example',load=lambda:fail)])
    with pytest.raises(ValueError) as error:integrations.export_extensions(tmp_path,receipt)
    assert 'SECRET' not in str(error.value) and 'retained' in str(error.value)
