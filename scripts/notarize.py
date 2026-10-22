"""Sign and notarize an existing Mac candidate on the maintainer's trusted Mac.

Credentials stay in Keychain. Signing creates a new package; original candidates
and their acceptance records are never modified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import shutil
import subprocess


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(*args):
    return subprocess.run(list(map(str, args)), check=True, capture_output=True,
                          text=True).stdout


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def verify_signatures(app, team):
    run('codesign', '--verify', '--deep', '--strict', app)
    paths = [app, app / 'Contents/MacOS/PodcastDubbing']
    paths += [app / 'Contents/Resources/bin' / name for name in ['uv', 'ffmpeg', 'ffprobe']]
    details = {}
    for path in paths:
        result = subprocess.run(['codesign', '-d', '--verbose=4', str(path)],
                                check=True, capture_output=True, text=True)
        description = result.stderr
        if (f'TeamIdentifier={team}\n' not in description
                or 'Authority=Developer ID Application:' not in description
                or 'runtime' not in description or 'Timestamp=' not in description):
            raise ValueError('Missing Developer ID, selected team, hardened runtime or timestamp: '
                             + str(path))
        details[str(path.relative_to(app))] = description
    return details


def archive(package):
    candidate = json.loads((package / 'candidate.json').read_text())
    target = package / candidate['archive']
    run('ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
        package / 'LocalDub.app', target)
    candidate['sha256'] = sha(target)
    write_json(package / 'candidate.json', candidate)
    (package / 'SHA256SUMS').write_text(candidate['sha256'] + '  ' + target.name + '\n')


def sign(args):
    if not re.fullmatch(r'[A-Fa-f0-9]{40}', args.identity):
        raise ValueError('Use the exact installed Developer ID certificate SHA-1')
    identities = run('security', 'find-identity', '-v', '-p', 'codesigning')
    expected = re.compile(re.escape(args.identity) + r' "Developer ID Application: [^"\n]+ \('
                          + re.escape(args.team) + r'\)"', re.IGNORECASE)
    if not expected.search(identities):
        raise ValueError('Identity must be a valid Developer ID Application for the selected team')
    original = json.loads((args.package / 'candidate.json').read_text())
    name = original['archive']
    if Path(name).name != name or not name.endswith('.zip'):
        raise ValueError('Invalid candidate archive name')
    if sha(args.package / name) != original['sha256']:
        raise ValueError('Original archive checksum differs from candidate')
    if args.output.exists():
        raise ValueError('Use a new signing output directory')
    args.output.mkdir(parents=True)
    # Extract the hashed archive rather than trusting a possibly changed sibling app.
    run('ditto', '-x', '-k', args.package / name, args.output)
    app = args.output / 'LocalDub.app'
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info['CFBundleShortVersionString'] != original['version']:
        raise ValueError('App version differs from candidate')
    resources = app / 'Contents/Resources'
    manifest_path = resources / 'bundle-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    actual = {str(p.relative_to(resources)): sha(p) for p in resources.rglob('*')
              if p.is_file() and p != manifest_path}
    if actual != manifest['files']:
        raise ValueError('App resource manifest mismatch before signing')
    options = ['--force', '--sign', args.identity, '--options', 'runtime', '--timestamp']
    for tool in ['uv', 'ffmpeg', 'ffprobe']:
        run('codesign', *options, resources / 'bin' / tool)
    run('codesign', *options, app / 'Contents/MacOS/PodcastDubbing')
    # Nested signatures change resource bytes; update hashes before sealing the app.
    manifest['files'] = {str(p.relative_to(resources)): sha(p)
                         for p in sorted(resources.rglob('*'))
                         if p.is_file() and p != manifest_path}
    write_json(manifest_path, manifest)
    run('codesign', *options, app)
    details = verify_signatures(app, args.team)
    write_json(args.output / 'signatures.json', details)
    original.update(signing='Developer ID; notarization pending', team_id=args.team,
                    signing_identity=args.identity.upper(), product_acceptance='pending')
    write_json(args.output / 'candidate.json', original)
    (args.output / 'Install.txt').write_text(
        'Notarization pending. Do not distribute this intermediate package.\n')
    archive(args.output)
    print('Developer ID candidate signed. Notarization is still required.', flush=True)


def notarize(args):
    package = args.package.resolve()
    candidate = json.loads((package / 'candidate.json').read_text())
    if candidate.get('signing') not in {'Developer ID; notarization pending',
                                       'Developer ID; notarized and stapled'}:
        raise ValueError('Sign the candidate with Developer ID first')
    app = package / 'LocalDub.app'
    verify_signatures(app, candidate['team_id'])
    if sha(package / candidate['archive']) != candidate['sha256']:
        raise ValueError('Signed candidate checksum changed')
    receipt = package / 'notary-submission.json'
    if not receipt.exists():
        submission = json.loads(run('xcrun', 'notarytool', 'submit',
            package / candidate['archive'], '--keychain-profile', args.profile,
            '--output-format', 'json', '--no-wait'))
        write_json(receipt, submission)
    submission = json.loads(receipt.read_text())
    result = json.loads(run('xcrun', 'notarytool', 'wait', submission['id'],
        '--keychain-profile', args.profile, '--output-format', 'json'))
    write_json(package / 'notary-result.json', result)
    if result.get('status') != 'Accepted':
        raise ValueError('Apple notarization was not accepted; inspect the submission log')
    run('xcrun', 'stapler', 'staple', app)
    run('xcrun', 'stapler', 'validate', app)
    write_json(package / 'signatures.json', verify_signatures(app, candidate['team_id']))
    assessment = subprocess.run(['spctl', '--assess', '--type', 'execute', '--verbose=4', str(app)],
                                check=True, capture_output=True, text=True)
    (package / 'gatekeeper.txt').write_text(assessment.stdout + assessment.stderr)
    candidate['signing'] = 'Developer ID; notarized and stapled'
    candidate['notarization_id'] = submission['id']
    write_json(package / 'candidate.json', candidate)
    (package / 'Install.txt').write_text(
        f"LocalDub {candidate['version']}\n\n"
        'Requires Apple Silicon and macOS 26 or later. Copy LocalDub.app to '
        'Applications, then open it. This app is Developer ID signed and Apple '
        'notarized. First setup downloads Python, dependencies and approximately '
        '8 GB of models; allow 25 GB free. Inference runs locally. The optional '
        'private CultureNOW plugin is supplied separately.\n')
    # The distribution archive must contain the stapled app, not the submission copy.
    archive(package)
    print('Apple accepted notarization. Stapling and Gatekeeper assessment passed.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    signing = commands.add_parser('sign')
    signing.add_argument('--package', type=Path, required=True)
    signing.add_argument('--output', type=Path, required=True)
    signing.add_argument('--identity', required=True)
    signing.add_argument('--team', required=True)
    notarization = commands.add_parser('notarize')
    notarization.add_argument('--package', type=Path, required=True)
    notarization.add_argument('--profile', required=True)
    args = parser.parse_args()
    try:
        (sign if args.command == 'sign' else notarize)(args)
    except (ValueError, subprocess.CalledProcessError) as error:
        detail = getattr(error, 'stderr', '') or ''
        parser.exit(1, str(error) + '\n' + detail)
