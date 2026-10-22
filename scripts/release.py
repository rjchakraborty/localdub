"""Build on a trusted Mac, then stage a verified candidate as a GitHub draft."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
CHECKS={'first_launch','native_ui','batch','file_and_url','mandarin','spanish',
        'cancel_resume','exports','privacy','listening_review','resource_usage'}
PREVIEW_PENDING={'first_launch','listening_review','resource_usage'}


def run(*args,**kwargs):return subprocess.run(list(map(str,args)),check=True,**kwargs)
def output(*args):return subprocess.check_output(list(map(str,args)),cwd=ROOT,text=True).strip()
def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def clean_commit():
    if output('git','status','--porcelain'):raise ValueError('Commit and review the complete source before release')
    return output('git','rev-parse','HEAD')


def verify_acceptance(candidate,acceptance,archive):
    if candidate['commit']!=acceptance.get('commit') or candidate['sha256']!=acceptance.get('sha256'):
        raise ValueError('Acceptance does not match this exact source and installer')
    if sha(archive)!=candidate['sha256']:raise ValueError('Installer checksum changed')
    channel=candidate.get('channel','stable')
    if channel not in {'stable','preview'} or acceptance.get('channel','stable')!=channel:
        raise ValueError('Candidate and acceptance release channels must match')
    checks=acceptance.get('checks',{})
    incomplete={key for key in CHECKS if checks.get(key) is not True}
    if channel=='stable' and incomplete:
        raise ValueError('Product acceptance is incomplete')
    if channel=='preview':
        pending=acceptance.get('pending',{})
        if incomplete-PREVIEW_PENDING:
            raise ValueError('Technical product acceptance is incomplete')
        if any(checks.get(key) is not False or not isinstance(pending.get(key),str)
               or not pending[key].strip() for key in incomplete):
            raise ValueError('Preview acceptance needs explicit pending checks and reasons')
    if not acceptance.get('evidence') or not acceptance.get('reviewed_at'):
        raise ValueError('Acceptance needs dated evidence references')
    if acceptance.get('secrets_reviewed') is not True:
        raise ValueError('Public source and artifact privacy review is incomplete')


def build(args):
    commit=clean_commit()
    if args.output.exists():raise ValueError('Use a new output directory')
    args.output.mkdir(parents=True)
    run(sys.executable,ROOT/'scripts/check_public_tree.py',cwd=ROOT)
    run(sys.executable,'-m','dubbing.desktop.build_media','--build-root',args.media_root,cwd=ROOT)
    encoder=os.environ.get('DUBBING_TEST_ENCODER') or shutil.which('ffmpeg')
    if not encoder:raise ValueError('A full FFmpeg encoder is required to create codec test fixtures')
    test_env={**os.environ,'DUBBING_TEST_ENCODER':encoder,'PATH':str(args.media_root.resolve()/'installed/bin')+os.pathsep+os.environ.get('PATH','')}
    run(sys.executable,'-m','pytest','-p','no:cacheprovider','--basetemp',args.output/'test-tmp',
        '--junitxml',args.output/'tests.xml',cwd=ROOT,env=test_env)
    run(sys.executable,'-m','dubbing.desktop.build','--output',args.output/'package',
        '--media-root',args.media_root,'--uv',args.uv,'--module-cache',args.output/'swift-cache',cwd=ROOT)
    if clean_commit()!=commit:raise ValueError('Source changed during build')
    archive=next((args.output/'package').glob('LocalDub-*-arm64.zip'))
    candidate={'commit':commit,'version':'0.1.0','archive':archive.name,'sha256':sha(archive),'channel':args.channel,
               'signing':'ad-hoc; not notarized','product_acceptance':'pending'}
    (archive.parent/'candidate.json').write_text(json.dumps(candidate,indent=2))
    (archive.parent/'SHA256SUMS').write_text(candidate['sha256']+'  '+archive.name+'\n')
    print('Build candidate prepared. Run product acceptance before staging a release.')


def stage(args):
    if not re.fullmatch(r'[\w.-]+/[\w.-]+',args.repo):raise ValueError('Expected owner/repository')
    candidate=json.loads((args.package/'candidate.json').read_text())
    acceptance=json.loads(args.acceptance.read_text())
    if Path(candidate['archive']).name!=candidate['archive'] or not candidate['archive'].endswith('.zip'):
        raise ValueError('Invalid installer filename')
    archive=args.package/candidate['archive']
    verify_acceptance(candidate,acceptance,archive)
    if clean_commit()!=candidate['commit']:raise ValueError('Checkout differs from accepted commit')
    account=output('gh','api','user','--jq','.login')
    if account!=args.repo.split('/')[0]:raise ValueError('Authenticated account is not the personal repository owner')
    repository=json.loads(output('gh','repo','view',args.repo,'--json','nameWithOwner,isFork'))
    if repository['nameWithOwner'].lower()!=args.repo.lower() or repository['isFork']:
        raise ValueError('Unexpected release destination')
    tag='v'+candidate['version']
    remote=output('git','ls-remote','https://github.com/'+args.repo+'.git','refs/tags/'+tag)
    if not remote or remote.split()[0]!=candidate['commit']:
        raise ValueError('Push the reviewed lightweight release tag for this commit first')
    # No automatic retry: an uncertain creation must be reconciled on GitHub.
    portable={**acceptance,'evidence':acceptance['evidence']}
    receipt=args.package/'acceptance.json';receipt.write_text(json.dumps(portable,indent=2))
    preview=['--prerelease'] if candidate.get('channel')=='preview' else []
    run('gh','release','create',tag,str(archive),str(args.package/'candidate.json'),
        str(args.package/'SHA256SUMS'),str(receipt),'--repo',args.repo,'--verify-tag',
        '--draft','--title','LocalDub '+tag+(' preview' if preview else ''),'--notes-file',args.notes,*preview)


if __name__=='__main__':
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build')
    b.add_argument('--channel',choices=['stable','preview'],default='stable')
    for name in ['output','media-root','uv']:b.add_argument('--'+name,type=Path,required=True)
    s=sub.add_parser('stage')
    s.add_argument('--repo',required=True)
    for name in ['package','acceptance','notes']:s.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args()
    try:(build if args.command=='build' else stage)(args)
    except (ValueError,subprocess.CalledProcessError) as exc:p.exit(1,str(exc)+'\n')
