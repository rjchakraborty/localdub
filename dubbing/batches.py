"""Durable URL batches using the existing single-worker job queue."""
import time
from functools import lru_cache
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from .pipeline import read, save
from .settings import LANGUAGES, Options, home
from .sources import public_url
from .languages import validate_language


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    sources: list[str] = Field(min_length=1, max_length=200)
    languages: list[str] = Field(min_length=1, max_length=len(LANGUAGES))
    options: Options


def path(batch_id):
    return home()/'batches'/str(UUID(str(batch_id)))/'batch.json'


def create(request):
    sources = list(dict.fromkeys(s.strip() for s in request.sources))
    languages = list(dict.fromkeys(request.languages))
    for language in languages:
        validate_language(language, request.options.tts_engine, request.options.translation_engine, request.options.quality)
    for source in sources:
        public_url(source)
    payload = {'sources': sources, 'languages': languages, 'options': request.options.model_dump()}
    return materialize(request.request_id, payload)


def materialize(request_id, payload, items=None, catalogue=None):
    target = path(request_id)
    if target.exists():
        previous = read(target)
        if previous['request'] != payload:
            raise ValueError('Batch request ID was already used with different settings')
        return describe(previous)
    # Jobs cannot run until the final manifest is atomically published.
    rows = []
    created = time.time()
    items = items or [{'id':str(i),'source':s} for i,s in enumerate(payload['sources'])]
    for index, item in enumerate(items):
        for language in payload['languages']:
            job_id = str(uuid5(request_id, f'{index}:{language}'))
            folder = home()/'jobs'/job_id
            folder.mkdir(parents=True, exist_ok=True)
            job = {'id': job_id, 'batch_id': str(request_id),
                   'source': item['source'], 'filename': None,
                   'catalogue_item_id':item['id'] if catalogue else None,
                   'catalogue_title':item.get('title'),
                   'options': {**payload['options'], 'language': language},
                   'status': 'queued', 'created': created + len(rows)*0.001, 'error': None}
            save(folder/'job.json', job)
            rows.append(job_id)
    batch = {'id': str(request_id), 'created': created, 'paused': False,
             'request': payload, 'jobs': rows}
    if catalogue:
        batch['catalogue'] = catalogue
    target.parent.mkdir(parents=True, exist_ok=True)
    save(target, batch)
    return describe(batch)


class CatalogueBatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    catalogue_id: UUID
    options: Options


def create_catalogue(request):
    from .catalogues import read_snapshot
    snapshot = read_snapshot(request.catalogue_id)
    payload = {'catalogue_id':str(request.catalogue_id), 'languages':[request.options.language],
               'options':request.options.model_dump()}
    return materialize(request.request_id, payload, snapshot['items'],
                       {'plugin':snapshot['plugin'],'provider':snapshot['provider'],'id':snapshot['id']})


def runnable(job):
    if not job.get('batch_id'):
        return True
    target = path(job['batch_id'])
    try:
        stamp = target.stat()
    except FileNotFoundError:
        return False
    return _runnable(target, stamp.st_mtime_ns, stamp.st_size)


@lru_cache(maxsize=100)
def _runnable(target, modified, size):
    return not read(target)['paused']


def describe(batch):
    counts = {}
    for job_id in batch['jobs']:
        target = home()/'jobs'/job_id/'job.json'
        stamp = target.stat()
        status = _status(target, stamp.st_mtime_ns, stamp.st_size)
        counts[status] = counts.get(status, 0) + 1
    return {'id': batch['id'], 'created': batch['created'], 'paused': batch['paused'],
            'counts': counts, 'total': len(batch['jobs']), 'jobs': batch['jobs']}


@lru_cache(maxsize=20000)
def _status(target, modified, size):
    return read(target)['status']


def control(batch_id, action):
    target = path(batch_id)
    batch = read(target)
    if action not in {'pause', 'resume', 'retry'}:
        raise ValueError('Unknown batch action')
    if action == 'retry':
        for job_id in batch['jobs']:
            folder = home()/'jobs'/job_id
            job = read(folder/'job.json')
            if job['status'] in {'failed', 'interrupted', 'cancelled'}:
                (folder/'cancel').unlink(missing_ok=True)
                job.update(status='queued', error=None)
                save(folder/'job.json', job)
    batch['paused'] = action == 'pause'
    save(target, batch)
    return describe(batch)
