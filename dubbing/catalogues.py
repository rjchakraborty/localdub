"""Opt-in plugin catalogue snapshots. Import metadata; never prefetch media."""
import re
import time
from importlib.metadata import entry_points
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from .integrations import load
from .pipeline import read, save
from .settings import home

MAX_ITEMS = 10000


class Item(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=1000)
    source: str = Field(min_length=1, max_length=4096)


def plugin(name):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', name) or name not in load().plugins:
        raise ValueError('Enable the catalogue source plugin first')
    matches = [p for p in entry_points(group='localdub.catalogues') if p.name == name]
    if len(matches) != 1:
        raise ValueError('Catalogue adapter is missing or ambiguous')
    folder = home().parent/'Plugins'/name
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return matches[0].load()(folder)


def providers():
    available = {p.name for p in entry_points(group='localdub.catalogues')}
    result = []
    for name in load().plugins:
        if name not in available:
            continue
        try:
            for row in plugin(name).providers():
                result.append({'plugin':name, 'id':str(row['id']),
                               'label':str(row['label']), 'configured':bool(row['configured'])})
        except Exception:
            result.append({'plugin':name, 'id':'unavailable', 'label':name+' · configuration unavailable', 'configured':False})
    return result


def snapshot_path(value):
    return home()/'catalogues'/str(UUID(str(value)))/'catalogue.json'


def scan(name, provider):
    adapter = plugin(name)
    if not any(p['id'] == provider and p['configured'] for p in adapter.providers()):
        raise ValueError('Catalogue provider is not configured')
    rows, seen = [], {}
    # Publish only after the complete iterator succeeds. Partial imports cannot run.
    for raw in adapter.scan(provider):
        row = Item.model_validate(raw).model_dump()
        from urllib.parse import urlsplit
        parts = urlsplit(row['source'])
        if parts.scheme not in {'https','http'} or not parts.hostname or parts.username or parts.password or parts.port not in {None,80,443}:
            raise ValueError('Catalogue contains an invalid source URL')
        # DNS and all redirects are checked again by the normal per-job downloader.
        if row['id'] in seen:
            if seen[row['id']] != row:
                raise ValueError('Catalogue repeats an ID with conflicting metadata')
            continue
        if len(rows) >= MAX_ITEMS:
            raise ValueError('Catalogue exceeds 10000 episodes; split the collection')
        rows.append(row); seen[row['id']] = row
    if not rows:
        raise ValueError('No playable podcasts found')
    value = {'id':str(uuid4()), 'plugin':name, 'provider':provider,
             'created':time.time(), 'items':rows}
    summary = {key:value for key,value in getattr(adapter,'summary',{}).items()
               if key in {'scanned','excluded_unpublished','excluded_no_audio'} and type(value) is int and value >= 0}
    value['summary'] = summary
    path = snapshot_path(value['id'])
    path.parent.mkdir(parents=True, mode=0o700)
    save(path, value)
    path.chmod(0o600)
    return {'id':value['id'], 'total':len(rows), 'summary':summary,
            'sample':[{'id':r['id'],'title':r['title']} for r in rows[:5]]}


def read_snapshot(value):
    return read(snapshot_path(value))
