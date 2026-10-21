"""Durable URL batches using the existing single-worker job queue."""
import time
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from .pipeline import read, save
from .settings import LANGUAGES, Options, home
from .sources import public_url


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    sources: list[str] = Field(min_length=1, max_length=200)
    languages: list[str] = Field(min_length=1, max_length=2)
    options: Options


def path(batch_id):
    return home()/'batches'/str(UUID(str(batch_id)))/'batch.json'


def create(request):
    sources = list(dict.fromkeys(s.strip() for s in request.sources))
    languages = list(dict.fromkeys(request.languages))
    if any(lang not in LANGUAGES for lang in languages):
        raise ValueError('Unsupported target language')
    for source in sources:
        public_url(source)
    payload = {'sources': sources, 'languages': languages, 'options': request.options.model_dump()}
    target = path(request.request_id)
    if target.exists():
        previous = read(target)
        if previous['request'] != payload:
            raise ValueError('Batch request ID was already used with different settings')
        return describe(previous)
    # Jobs cannot run until the final manifest is atomically published.
    rows = []
    created = time.time()
    for index, source in enumerate(sources):
        for language in languages:
            job_id = str(uuid5(request.request_id, f'{index}:{language}'))
            folder = home()/'jobs'/job_id
            folder.mkdir(parents=True, exist_ok=True)
            job = {'id': job_id, 'batch_id': str(request.request_id),
                   'source': source, 'filename': None,
                   'options': {**payload['options'], 'language': language},
                   'status': 'queued', 'created': created + len(rows)*0.001, 'error': None}
            save(folder/'job.json', job)
            rows.append(job_id)
    batch = {'id': str(request.request_id), 'created': created, 'paused': False,
             'request': payload, 'jobs': rows}
    target.parent.mkdir(parents=True, exist_ok=True)
    save(target, batch)
    return describe(batch)


def runnable(job):
    if not job.get('batch_id'):
        return True
    target = path(job['batch_id'])
    return target.exists() and not read(target)['paused']


def describe(batch):
    jobs = [read(home()/'jobs'/job_id/'job.json') for job_id in batch['jobs']]
    counts = {}
    for job in jobs:
        counts[job['status']] = counts.get(job['status'], 0) + 1
    return {'id': batch['id'], 'created': batch['created'], 'paused': batch['paused'],
            'counts': counts, 'total': len(jobs), 'jobs': batch['jobs']}


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
