import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import numpy as np
import pytest
import soundfile as sf

from dubbing.exports import export_job, safe_title
from dubbing.podbean import podbean_episode
from dubbing.settings import home, Options


@pytest.fixture
def workspace(tmp_path,monkeypatch):
    monkeypatch.setenv('DUBBING_DESKTOP_WORKSPACE',str(tmp_path))
    monkeypatch.delenv('DUBBING_HOME',raising=False)
    return tmp_path


def test_desktop_home_is_selected_and_missing_storage_never_falls_back(workspace,monkeypatch):
    assert home()==workspace/'Jobs'
    monkeypatch.setenv('DUBBING_DESKTOP_WORKSPACE',str(workspace/'disconnected'))
    with pytest.raises(RuntimeError,match='unavailable'):home()


def test_conflicting_desktop_and_developer_paths_rejected(workspace,monkeypatch):
    monkeypatch.setenv('DUBBING_HOME',str(workspace/'other'))
    with pytest.raises(RuntimeError,match='disagree'):home()


def test_dynamic_host_guard_and_preferences_survive_new_client(workspace,monkeypatch):
    from dubbing.server import app
    monkeypatch.setenv('DUBBING_DESKTOP_PORT','49151')
    client=TestClient(app)
    assert client.get('/api/config',headers={'host':'127.0.0.1:8092'}).status_code==403
    config=client.get('/api/config',headers={'host':'127.0.0.1:49151'}).json()
    headers={'host':'127.0.0.1:49151','x-dubbing-token':config['token']}
    assert client.post('/api/preferences',json=Options(language='es',temperature=.7).model_dump(),headers=headers).status_code==200
    assert TestClient(app).get('/api/preferences',headers=headers).json()['options']['language']=='es'
    assert client.post('/api/preferences',json={'language':'fr'},headers=headers).status_code==422
    assert client.post('/api/preferences',json={'language':'zh'},headers={'host':'127.0.0.1:49151'}).status_code==403


def test_corrupt_preferences_load_defaults_without_erasing_file(workspace):
    from dubbing.server import app
    path=home()/'preferences.json';path.write_text('{broken')
    response=TestClient(app).get('/api/preferences').json()
    assert response['options']['language']=='zh' and response['warning']
    assert path.read_text()=='{broken'


@pytest.mark.parametrize('host',['example.podbean.com','podbean.com','www.podbean.com'])
def test_podbean_graph_enclosure_and_title_without_html_title(host):
    html='<script type="application/ld+json">'+json.dumps({'@graph':[{'@type':'PodcastEpisode','name':'Episode','url':'/e/episode/','associatedMedia':{'contentUrl':'https://mcdn.podbean.com/example.mp3'}}]})+'</script>'
    assert podbean_episode(html,'https://'+host+'/e/episode/')['title']=='Episode'


def test_podbean_homepage_needs_specific_episode(workspace,monkeypatch):
    from dubbing.sources import resolve
    from dubbing.integrations import set_podbean
    from dubbing import sources
    set_podbean(True)
    monkeypatch.setattr(sources,'public_url',lambda url:url)
    with pytest.raises(ValueError,match='specific Podbean episode'):resolve('https://example.podbean.com/',workspace)


def test_html_cannot_be_mistaken_for_audio(tmp_path):
    from dubbing.audio import probe
    path=tmp_path/'input.audio';path.write_text('<html><title>Not an audio file</title></html>')
    with pytest.raises(ValueError,match='not readable standalone audio'):probe(path)


@pytest.mark.parametrize('value',[
    [],
    [{'@type':'PodcastSeries','associatedMedia':{'contentUrl':'https://example.com/a.mp3'}}],
    [{'@type':'PodcastEpisode','associatedMedia':{'contentUrl':'file:///etc/passwd'}}],
    [{'@type':'PodcastEpisode','url':{'invalid':'type'},'associatedMedia':{'contentUrl':'https://example.com/a.mp3'}}],
    [{'@type':'PodcastEpisode','associatedMedia':[{'contentUrl':'https://example.com/a.mp3'},{'contentUrl':'https://example.com/b.mp3'}]}],
])
def test_unsupported_or_ambiguous_podbean_metadata_rejected(value):
    with pytest.raises(ValueError):podbean_episode('<script type="application/ld+json">'+json.dumps(value)+'</script>','https://example.podbean.com/e/episode/')


@pytest.mark.parametrize('batch', [False, True])
def test_named_export_is_idempotent_and_never_overwrites_modified_bundle(workspace, batch):
    from dubbing.audio import command
    folder=home()/'jobs'/str(uuid4());folder.mkdir(parents=True)
    job={'id':folder.name,'created':1792580000,'status':'completed','options':Options(language='es').model_dump()}
    if batch:job['batch_id']=str(uuid4())
    (folder/'job.json').write_text(json.dumps(job))
    (folder/'source.json').write_text(json.dumps({'title':'../Sample Episode: Podcast'}))
    sf.write(folder/'dubbed.wav',np.sin(np.arange(24000)*2*np.pi*220/24000)*.1,24000)
    command(['ffmpeg','-nostdin','-v','error','-y','-i',str(folder/'dubbed.wav'),'-codec:a','libmp3lame',str(folder/'dubbed.mp3')])
    for name in ['report.json','audit.json','translation.json']:(folder/name).write_text('{}')
    (folder/'translated.vtt').write_text('WEBVTT\n')
    first=export_job(folder);second=export_job(folder)
    assert first==second
    target=Path(first['folder']);assert target.is_relative_to(workspace/'Exports')
    if batch:assert target.is_relative_to(workspace/'Exports'/'Batches'/job['batch_id'])
    mp3=target/'-Sample Episode- Podcast-Spanish.mp3'
    assert mp3.exists() and mp3.read_bytes()==(folder/'dubbed.mp3').read_bytes()
    mp3.write_bytes(b'externally modified bundle')
    with pytest.raises(ValueError,match='changed'):export_job(folder)
    assert mp3.read_bytes()==b'externally modified bundle'
    assert not list(target.parent.glob('*.exporting'))


@pytest.mark.parametrize('title',['../../','\x00/../', '很长的名字'*100])
def test_export_component_cannot_escape_or_exceed_filename_bytes(title):
    result=safe_title(title)
    assert result not in {'','.', '..'} and '/' not in result and len(result.encode())<=160


def test_independent_process_waits_for_compute_slot(tmp_path,monkeypatch):
    import os,subprocess,sys,time
    from dubbing.resources import compute_slot
    monkeypatch.setenv('DUBBING_COMPUTE_LOCK',str(tmp_path/'compute.lock'))
    marker=tmp_path/'acquired';waiting=tmp_path/'waiting'
    code='from dubbing.resources import compute_slot;from pathlib import Path;import sys\nwith compute_slot(lambda:Path(sys.argv[2]).touch()):Path(sys.argv[1]).touch()'
    with compute_slot(lambda:None):
        process=subprocess.Popen([sys.executable,'-B','-c',code,str(marker),str(waiting)],env=os.environ.copy())
        deadline=time.monotonic()+5
        while not waiting.exists() and time.monotonic()<deadline:time.sleep(.01)
        assert waiting.exists() and not marker.exists()
    assert process.wait(timeout=5)==0 and marker.exists()
