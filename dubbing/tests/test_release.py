import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('release',Path(__file__).resolve().parents[2]/'scripts/release.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)


def test_release_rejects_missing_product_acceptance_and_changed_installer(tmp_path):
    archive=tmp_path/'app.zip';archive.write_bytes(b'test archive bytes')
    candidate={'commit':'a'*40,'sha256':release.sha(archive)}
    acceptance={**candidate,'checks':{},'evidence':['public validation record'],'reviewed_at':'2026-10-21','secrets_reviewed':True}
    with pytest.raises(ValueError,match='incomplete'):release.verify_acceptance(candidate,acceptance,archive)
    acceptance['checks']={key:True for key in release.CHECKS}
    release.verify_acceptance(candidate,acceptance,archive)
    archive.write_bytes(b'changed')
    with pytest.raises(ValueError,match='checksum'):release.verify_acceptance(candidate,acceptance,archive)
