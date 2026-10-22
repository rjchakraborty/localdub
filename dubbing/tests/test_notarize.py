import argparse
import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('notarize', Path(__file__).resolve().parents[2]/'scripts/notarize.py')
notarize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notarize)


def test_sign_rejects_ad_hoc_and_wrong_team_before_output(tmp_path, monkeypatch):
    args = argparse.Namespace(identity='-', team='PERSONAL01', output=tmp_path/'signed')
    with pytest.raises(ValueError, match='exact installed'):
        notarize.sign(args)
    args.identity = 'A'*40
    monkeypatch.setattr(notarize, 'run', lambda *args: '1) ' + 'A'*40 +
                        ' "Developer ID Application: Someone (OTHERTEAM1)"\n')
    with pytest.raises(ValueError, match='selected team'):
        notarize.sign(args)
    assert not args.output.exists()


def test_notarize_rejects_unsigned_candidate_without_submitting(tmp_path, monkeypatch):
    (tmp_path/'candidate.json').write_text(json.dumps({'signing': 'ad-hoc; not notarized'}))
    def unexpected(*args):
        pytest.fail('Unsigned candidate reached an external command')
    monkeypatch.setattr(notarize, 'run', unexpected)
    with pytest.raises(ValueError, match='Developer ID first'):
        notarize.notarize(argparse.Namespace(package=tmp_path, profile='unused'))


def test_notarize_reuses_submission_and_rejects_invalid_result(tmp_path, monkeypatch):
    payload = tmp_path/'LocalDub.zip'
    payload.write_bytes(b'unchanged submission')
    candidate = {'signing': 'Developer ID; notarization pending', 'team_id': 'PERSONAL01',
                 'archive': payload.name, 'sha256': notarize.sha(payload)}
    (tmp_path/'candidate.json').write_text(json.dumps(candidate))
    (tmp_path/'notary-submission.json').write_text(json.dumps({'id': 'existing-id'}))
    calls = []
    def command(*args):
        calls.append(args)
        assert args[:3] == ('xcrun', 'notarytool', 'wait')
        return json.dumps({'id': 'existing-id', 'status': 'Invalid'})
    monkeypatch.setattr(notarize, 'run', command)
    monkeypatch.setattr(notarize, 'verify_signatures', lambda *args: {})
    with pytest.raises(ValueError, match='not accepted'):
        notarize.notarize(argparse.Namespace(package=tmp_path, profile='local-keychain'))
    assert len(calls) == 1
    assert calls[0][3] == 'existing-id'
    assert json.loads((tmp_path/'candidate.json').read_text()) == candidate
    assert not (tmp_path/'Install.txt').exists()
