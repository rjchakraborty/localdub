"""Named, immutable local podcast export bundles."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import unicodedata
from uuid import uuid4

from .settings import home
from .privacy import public_metadata

LABELS={'zh':'Mandarin','es':'Spanish'}
EXPORT_FILES=['dubbed.mp3','dubbed.wav','translated.vtt','report.json','audit.json','translation.json','source.json']


def read(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def safe_title(value):
    text=unicodedata.normalize('NFKC',str(value or 'Podcast'))
    text=''.join(c for c in text if not unicodedata.category(c).startswith('C'))
    text=re.sub(r'[\\/:*?"<>|]+','-',text)
    text=re.sub(r'\s+',' ',text).strip(' .')
    return text.encode('utf8')[:160].decode('utf8',errors='ignore').strip(' .') or 'Podcast'


def download_name(folder,name):
    job=read(folder/'job.json')
    source=read(folder/'source.json') if (folder/'source.json').exists() else {}
    title=source.get('title') or job.get('filename') or 'Podcast'
    if job.get('filename') and title==job['filename']:title=Path(title).stem
    title=safe_title(public_metadata(title))
    stem=title+'-'+LABELS[job['options']['language']]
    if name.startswith('dubbed.') or name=='translated.vtt':return stem+Path(name).suffix
    return stem+'-'+name


def export_job(folder):
    job=read(folder/'job.json')
    if job['status'] not in {'completed','needs_review'}:raise ValueError('Finish the job before exporting')
    for name in EXPORT_FILES:
        if not (folder/name).is_file():raise ValueError('Export file is unavailable: '+name)
    workspace=os.environ.get('DUBBING_DESKTOP_WORKSPACE')
    # home() validates either the selected desktop workspace or developer disk.
    current_home=home()
    root=Path(workspace).resolve()/'Exports' if workspace else current_home/'exports'
    if job.get('batch_id'):
        from uuid import UUID
        root = root/'Batches'/str(UUID(job['batch_id']))
    source=read(folder/'source.json');raw_title=source.get('title') or job.get('filename')
    if job.get('filename') and raw_title==job['filename']:raw_title=Path(raw_title).stem
    title=safe_title(public_metadata(raw_title))
    audio_hash=digest(folder/'dubbed.mp3')
    stamp=datetime.fromtimestamp(job['created'],timezone.utc).strftime('%Y%m%d-%H%M%S')
    parent=root/title/LABELS[job['options']['language']].lower()
    version=stamp+'-'+job['id'][:8]+'-'+audio_hash[:8]
    target=parent/version
    if target.exists():
        receipt=read(target/'export-manifest.json')
        if receipt['job_id']!=job['id'] or receipt['audio_sha256']!=audio_hash:raise ValueError('Export version conflicts with existing data')
        if not all(digest(target/name)==expected for name,expected in receipt['files'].items()):raise ValueError('Existing export changed; original bundle preserved')
        return {**receipt,'folder':str(target)}
    parent.mkdir(parents=True,exist_ok=True)
    temporary=parent/('.'+str(uuid4())+'.exporting');temporary.mkdir()
    try:
        files={}
        for name in EXPORT_FILES:
            named=download_name(folder,name)
            if name.endswith('.json'):
                original=(folder/name).read_bytes()
                sanitized=json.dumps(public_metadata(json.loads(original)),ensure_ascii=False,indent=2).encode()
                (temporary/named).write_bytes(sanitized)
                if (folder/name).read_bytes()!=original:
                    raise ValueError('Report changed during export; retry after processing stops')
            else:
                shutil.copyfile(folder/name,temporary/named)
            sha=digest(temporary/named)
            if not name.endswith('.json') and sha!=digest(folder/name):raise ValueError('Audio/report changed during export; retry after processing stops')
            files[named]=sha
        receipt={'job_id':job['id'],'title':source.get('title') or job.get('filename'),'language':job['options']['language'],'status':job['status'],'audio_sha256':audio_hash,'files':files,'quality_note':'Automated checks do not establish bilingual meaning, voice identity or preserved emotion; listening review remains necessary.'}
        receipt=public_metadata(receipt)
        (temporary/'export-manifest.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
        temporary.rename(target)
        return {**receipt,'folder':str(target)}
    finally:
        if temporary.exists():shutil.rmtree(temporary)
