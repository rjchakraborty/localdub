"""Check release source paths and obvious credentials without printing secrets."""
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
BLOCKED={'.env','.envrc','integrations.json','credentials.json','service-account.json'}
DIRS={'.venv','venv','__pycache__','Jobs','Models','Exports','Runtime','Cache','private_plugins'}
PATTERNS=[r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
          r'\bAKIA[0-9A-Z]{16}\b',r'\bgh[pousr]_[A-Za-z0-9]{30,}\b',
          r'"private_key"\s*:\s*"[^"\n]{20,}',
          r'(?i)(?:X-Amz-Signature|X-Goog-Signature)=[a-f0-9]{32,}']


def check(root=ROOT):
    raw=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=root)
    names=sorted(set(raw.decode().split('\0'))-{''})
    failures=[]
    for name in names:
        path=root/name
        if path.is_symlink():failures.append((name,'symlink'));continue
        if path.name in BLOCKED or any(part in DIRS for part in path.parts):
            failures.append((name,'private/runtime file'));continue
        if path.suffix.lower() in {'.mp3','.wav','.m4a','.pem','.p12','.key','.safetensors','.npz'}:
            failures.append((name,'media/model/key file'));continue
        if not path.is_file():continue
        try:text=path.read_text()
        except UnicodeDecodeError:
            failures.append((name,'unreviewed binary'));continue
        if any(re.search(pattern,text) for pattern in PATTERNS):failures.append((name,'credential pattern'))
    for name,reason in failures:print(f'FAIL {name}: {reason}')
    print(f'Public source scan: {len(names)} files, {len(failures)} failures')
    return not failures


if __name__=='__main__':sys.exit(0 if check() else 1)
