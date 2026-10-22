from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from dubbing import batches
from dubbing.pipeline import read, save


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv('DUBBING_DESKTOP_WORKSPACE', str(tmp_path))
    monkeypatch.delenv('DUBBING_HOME', raising=False)
    monkeypatch.setattr(batches, 'public_url', lambda value: value)
    return tmp_path/'Jobs'


def request(**values):
    return batches.BatchRequest(**{'request_id':uuid4(), 'sources':['https://example.com/audio.mp3'],
        'languages':['zh','es'], 'options':{'language':'zh'}, **values})


def test_durable_matrix_dedup_and_idempotent_retry(root):
    req=request(sources=['https://example.com/audio.mp3']*2)
    first=batches.create(req)
    assert first['total']==2
    assert batches.create(req)==first
    assert len(list((root/'jobs').iterdir()))==2
    req.options.temperature=.9
    with pytest.raises(ValueError, match='different settings'):
        batches.create(req)


def test_pause_and_retry_preserve_success(root):
    result=batches.create(request())
    paths=[root/'jobs'/job/'job.json' for job in result['jobs']]
    for path,status in zip(paths,['completed','failed']):
        job=read(path);job['status']=status;save(path,job)
    batches.control(result['id'],'pause')
    assert not batches.runnable(read(paths[1]))
    result=batches.control(result['id'],'retry')
    assert result['counts']=={'completed':1,'queued':1}
    assert batches.runnable(read(paths[1]))


def test_unpublished_manifest_never_runs(root):
    assert not batches.runnable({'batch_id':str(uuid4())})


def test_invalid_language_creates_nothing(root):
    with pytest.raises(ValueError, match='Unsupported'):
        batches.create(request(languages=['ar']))
    assert not (root/'jobs').exists()


def test_api_auth_and_persistence(root):
    from dubbing.server import app, TOKEN
    client=TestClient(app)
    payload=request().model_dump(mode='json')
    assert client.post('/api/batches',json=payload).status_code==403
    response=client.post('/api/batches',json=payload,headers={'x-dubbing-token':TOKEN})
    assert response.status_code==201
    assert client.get('/api/batches').json()[0]['total']==2
    assert client.post('/api/batches/'+response.json()['id']+'/pause',headers={'x-dubbing-token':TOKEN}).json()['paused']
