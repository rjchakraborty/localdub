"""Every test owns temporary state; never use a developer's real workspace."""
import pytest


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path,monkeypatch):
    workspace=tmp_path/'workspace';workspace.mkdir()
    monkeypatch.setenv('DUBBING_DESKTOP_WORKSPACE',str(workspace))
    monkeypatch.delenv('DUBBING_HOME',raising=False)
    monkeypatch.setenv('LOCALDUB_CONFIG',str(workspace/'integrations.json'))
    monkeypatch.setenv('DUBBING_COMPUTE_LOCK',str(workspace/'compute.lock'))
