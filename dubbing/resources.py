"""One heavy dubbing pipeline per Mac user, including separate app workspaces."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path


@contextmanager
def compute_slot(on_wait):
    configured=os.environ.get('DUBBING_COMPUTE_LOCK')
    path=Path(configured) if configured else Path.home()/'Library/Application Support/LocalDub/compute.lock'
    if not path.is_absolute():raise ValueError('Compute lock must have an absolute path')
    path.parent.mkdir(parents=True,exist_ok=True)
    descriptor=os.open(path,os.O_CREAT|os.O_RDWR,0o600)
    with os.fdopen(descriptor,'a') as handle:
        try:
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                on_wait()
                fcntl.flock(handle,fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(handle,fcntl.LOCK_UN)
