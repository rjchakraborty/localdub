import os

from dubbing.desktop.bootstrap import downloaded_bytes


def test_resumed_progress_excludes_orphan_partials_and_duplicate_complete_blob(tmp_path):
    blobs=tmp_path/'blobs';blobs.mkdir()
    snapshot=tmp_path/'snapshots/reviewed';snapshot.mkdir(parents=True)
    model={'revision':'reviewed','files':[
        {'name':'weights.safetensors','bytes':100,'sha256':'weights'},
        {'name':'tokenizer.safetensors','bytes':40,'sha256':'tokenizer'},
        {'name':'config.json','bytes':2,'sha256':None},
    ]}
    (blobs/'weights.incomplete').write_bytes(b'x'*30)
    (blobs/'unrelated-old-revision.incomplete').write_bytes(b'x'*200)
    (blobs/'tokenizer').write_bytes(b'x'*40)
    (blobs/'tokenizer.incomplete').write_bytes(b'x'*40)
    (snapshot/'tokenizer.safetensors').symlink_to('../../blobs/tokenizer')
    (snapshot/'config.json').write_text('{}')
    assert downloaded_bytes(model,tmp_path)==72
    (blobs/'weights.oldretry.incomplete').write_bytes(b'x'*20)
    os.utime(blobs/'weights.oldretry.incomplete',ns=(1,1))
    (blobs/'weights.1e523acd.incomplete').write_bytes(b'x'*60)
    assert downloaded_bytes(model,tmp_path)==102
    (blobs/'weights.newretry.incomplete').write_bytes(b'x'*10)
    assert downloaded_bytes(model,tmp_path)==52
    (blobs/'weights.incomplete').rename(blobs/'weights')
    (blobs/'weights').write_bytes(b'x'*100)
    assert downloaded_bytes(model,tmp_path)==142
