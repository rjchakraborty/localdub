"""Download pinned desktop models with progress, validation and resumable caches."""
import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor

from huggingface_hub import HfApi, snapshot_download
from dubbing.models import REVISIONS
from dubbing.settings import ASR_MODEL, TTS_MODELS

DEFAULT_MODELS=[ASR_MODEL, 'mlx-community/Hy-MT2-7B-4bit', TTS_MODELS['balanced']]
PATTERNS=['*.json','*.safetensors','*.npz','*.tiktoken','*.txt','*.model','*.jinja','LICENSE*','README.md']


def emit(event, **values):
    print(json.dumps({'event':event,**values},ensure_ascii=False),flush=True)


def model_plan():
    api=HfApi(token=False)
    result=[]
    for name in DEFAULT_MODELS:
        revision=REVISIONS[name]
        info=api.model_info(name,revision=revision,files_metadata=True)
        if info.sha!=revision:
            raise ValueError('Model revision mismatch: '+name)
        files=[]
        for item in info.siblings:
            if not any(fnmatch.fnmatch(item.rfilename,pattern) for pattern in PATTERNS):
                continue
            path=Path(item.rfilename)
            if path.is_absolute() or '..' in path.parts or item.size is None:
                raise ValueError('Invalid model file metadata: '+name)
            files.append({'name':item.rfilename,'bytes':item.size,'sha256':item.lfs.sha256 if item.lfs else None})
        if not files or not any(f['name'].endswith(('.safetensors','.npz')) for f in files):
            raise ValueError('Model has no reviewed weights: '+name)
        result.append({'model':name,'revision':revision,'total_bytes':sum(f['bytes'] for f in files),'files':files})
    return result


def file_digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle,'sha256').hexdigest()


def installed(receipt, cache):
    if not receipt.is_file():
        return False
    try:
        data=json.loads(receipt.read_text())
        if data['revisions']!={name:REVISIONS[name] for name in DEFAULT_MODELS}:
            return False
        if {model['model'] for model in data['models']} != set(DEFAULT_MODELS):
            return False
        for model in data['models']:
            snapshot=Path(model['snapshot'])
            expected=cache/('models--'+model['model'].replace('/','--'))/'snapshots'/REVISIONS[model['model']]
            if snapshot!=expected or snapshot.name!=model['revision']:
                return False
            for item in model['files']:
                path=snapshot/item['name']
                if not path.resolve().is_relative_to(cache) or path.stat().st_size!=item['bytes']:
                    return False
        return len(data['models'])==len(DEFAULT_MODELS)
    except (OSError,ValueError,KeyError,TypeError):
        return False


def install(workspace):
    if not workspace.is_absolute():
        raise ValueError('Workspace must be an absolute user-selected path')
    workspace=workspace.resolve()
    cache=workspace/'Models'/'hub'
    receipt=workspace/'Runtime'/'models-ready.json'
    if installed(receipt,cache):
        emit('models_ready',cached=True)
        return
    plan=model_plan()
    required=sum(m['total_bytes'] for m in plan)
    emit('model_plan',total_bytes=required,models=len(plan))
    cache.mkdir(parents=True,exist_ok=True)
    completed=0
    with ThreadPoolExecutor(max_workers=1) as pool:
        for index,model in enumerate(plan):
            repository=cache/('models--'+model['model'].replace('/','--'))
            emit('model_start',model=model['model'],index=index,total_models=len(plan))
            task=pool.submit(snapshot_download,model['model'],revision=model['revision'],cache_dir=cache,allow_patterns=[f['name'] for f in model['files']],max_workers=2,token=False)
            while not task.done():
                blobs=repository/'blobs'
                downloaded=sum(p.stat().st_size for p in blobs.glob('*') if p.is_file() and not p.is_symlink()) if blobs.exists() else 0
                emit('model_progress',model=model['model'],completed_bytes=completed+min(downloaded,model['total_bytes']),total_bytes=required)
                time.sleep(.5)
            snapshot=Path(task.result()).resolve()
            if snapshot.name!=model['revision'] or not snapshot.is_relative_to(cache):
                raise ValueError('Unexpected downloaded snapshot')
            emit('model_verify',model=model['model'])
            for item in model['files']:
                path=snapshot/item['name']
                if not path.resolve().is_relative_to(cache) or path.stat().st_size!=item['bytes']:
                    raise ValueError('Model file size/path mismatch: '+item['name'])
                digest=file_digest(path)
                if item['sha256'] and digest!=item['sha256']:
                    raise ValueError('Model checksum mismatch: '+item['name'])
                item['downloaded_sha256']=digest
            model['snapshot']=str(snapshot)
            completed+=model['total_bytes']
            emit('model_progress',completed_bytes=completed,total_bytes=required)
    receipt.parent.mkdir(parents=True,exist_ok=True)
    temporary=receipt.with_suffix('.tmp')
    temporary.write_text(json.dumps({'revisions':{name:REVISIONS[name] for name in DEFAULT_MODELS},'models':plan},indent=2))
    temporary.replace(receipt)
    emit('models_ready',cached=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--inspect',action='store_true')
    parser.add_argument('--workspace',type=Path)
    args=parser.parse_args()
    if args.inspect:
        plan=model_plan()
        emit('metadata_inspection',models=[{k:v for k,v in model.items() if k!='files'} for model in plan],total_bytes=sum(m['total_bytes'] for m in plan),scope='Public metadata only; no model or runtime installation performed')
    elif args.workspace:
        install(args.workspace)
    else:
        parser.error('--workspace is required for setup')
