"""Catalogue completeness, durable scale and paging regressions (no inference)."""
from uuid import uuid4
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from dubbing import catalogues, batches
from dubbing.pipeline import read, save


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv('DUBBING_DESKTOP_WORKSPACE',str(tmp_path))
    monkeypatch.delenv('DUBBING_HOME',raising=False)
    monkeypatch.setattr(catalogues,'load',lambda:SimpleNamespace(plugins=['example']))
    return tmp_path/'Jobs'


def adapter(monkeypatch, rows):
    class Provider:
        def providers(self):return [{'id':'all','label':'Example collection','configured':True}]
        def scan(self, provider):yield from rows
    entry=SimpleNamespace(name='example',load=lambda:lambda folder:Provider())
    monkeypatch.setattr(catalogues,'entry_points',lambda **kwargs:[entry])


def test_full_2000_metadata_and_durable_single_language_batch(root,monkeypatch):
    adapter(monkeypatch,({'id':str(i),'title':f'Episode {i}','source':f'https://example.com/{i}.mp3'} for i in range(2000)))
    snapshot=catalogues.scan('example','all')
    assert snapshot['total']==2000 and len(snapshot['sample'])==5
    assert not (root/'jobs').exists()  # Import never downloads or starts audio.
    request=batches.CatalogueBatchRequest(request_id=uuid4(),catalogue_id=snapshot['id'],options={'language':'es'})
    result=batches.create_catalogue(request)
    assert result['total']==2000 and result['counts']=={'queued':2000}
    assert batches.create_catalogue(request)==result
    first=root/'jobs'/result['jobs'][0]/'job.json'
    job=read(first);job['status']='completed';save(first,job)
    batches.control(result['id'],'pause')
    assert not batches.runnable(job)
    retried=batches.control(result['id'],'retry')
    assert retried['counts']=={'completed':1,'queued':1999}
    assert batches.runnable(read(first))
    assert all(p.name=='job.json' for p in (root/'jobs').glob('*/*'))


def test_partial_provider_failure_never_publishes(root,monkeypatch):
    def broken():
        yield {'id':'1','title':'One','source':'https://example.com/a.mp3'}
        raise ValueError('Page two failed')
    adapter(monkeypatch,broken())
    with pytest.raises(ValueError,match='Page two'):catalogues.scan('example','all')
    assert not (root/'catalogues').exists()


def test_conflicting_duplicate_and_disabled_plugin(root,monkeypatch):
    adapter(monkeypatch,[{'id':'1','title':str(i),'source':'https://example.com/a.mp3'} for i in range(2)])
    with pytest.raises(ValueError,match='conflicting'):catalogues.scan('example','all')
    with pytest.raises(ValueError,match='Enable'):catalogues.scan('disabled','all')


def test_api_secrets_redacted_and_pagination(root,monkeypatch):
    from dubbing.server import app,TOKEN
    client=TestClient(app)
    def fail(*args):raise ValueError('password=SECRET access_token=SECRET')
    monkeypatch.setattr(catalogues,'scan',fail)
    body={'plugin':'example','provider':'all'}
    assert client.post('/api/catalogues/scan',json=body).status_code==403
    reply=client.post('/api/catalogues/scan',json=body,headers={'x-dubbing-token':TOKEN})
    assert reply.status_code==422 and 'SECRET' not in reply.text
    monkeypatch.setattr(batches,'public_url',lambda value:value)
    result=batches.create(batches.BatchRequest(request_id=uuid4(),sources=[f'https://example.com/{i}' for i in range(75)],languages=['zh'],options={'language':'zh'}))
    assert len(client.get('/api/jobs').json())==50
    assert len(client.get('/api/jobs?offset=50').json())==25
    assert client.get('/api/jobs?limit=1000').status_code==422
    assert len({j['id'] for j in client.get('/api/jobs').json()+client.get('/api/jobs?offset=50').json()})==75


def test_listing_cache_observes_status_change(root,monkeypatch):
    from dubbing.server import job_listing
    monkeypatch.setattr(batches,'public_url',lambda value:value)
    result=batches.create(batches.BatchRequest(request_id=uuid4(),sources=['https://example.com/a'],languages=['zh'],options={'language':'zh'}))
    path=root/'jobs'/result['jobs'][0]/'job.json'
    assert job_listing()[0][1]['status']=='queued'
    row=read(path);row['status']='cancelled';save(path,row)
    assert job_listing()[0][1]['status']=='cancelled'
    assert batches.describe(read(batches.path(result['id'])))['counts']=={'cancelled':1}


def test_low_storage_pauses_before_downloading(root,monkeypatch):
    import asyncio
    from dubbing.server import Queue
    monkeypatch.setattr(batches,'public_url',lambda value:value)
    monkeypatch.setattr('dubbing.server.shutil.disk_usage',lambda path:SimpleNamespace(free=0))
    result=batches.create(batches.BatchRequest(request_id=uuid4(),sources=['https://example.com/a'],languages=['zh'],options={'language':'zh'}))
    async def check():
        queue=Queue();task=asyncio.create_task(queue.work())
        await asyncio.sleep(.05)
        assert queue.process is None
        assert read(batches.path(result['id']))['paused']
        assert not list(root.glob('jobs/*/input.audio'))
        task.cancel()
        try:await task
        except asyncio.CancelledError:pass
    asyncio.run(check())
