"""Package the native window, Python sources and standalone tools as a Mac app."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tomllib
import urllib.request

VERSION=tomllib.loads((Path(__file__).resolve().parents[2]/'pyproject.toml').read_text())['project']['version']
UV_VERSION='0.11.19'


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def build(output,media,uv,module_cache):
    output=output.resolve();media=media.resolve();uv=uv.resolve()
    if output.exists():raise ValueError('Use a new build directory; existing app bundles are preserved')
    version=subprocess.check_output([str(uv),'--version'],text=True)
    if not version.startswith('uv '+UV_VERSION+' '):raise ValueError('Expected reviewed uv '+UV_VERSION)
    output.mkdir(parents=True)
    app=output/'LocalDub.app';contents=app/'Contents';resources=contents/'Resources'
    for path in [contents/'MacOS',resources/'bin',resources/'Backend/dubbing/desktop',resources/'Notices/Source']:
        path.mkdir(parents=True)
    source=Path(__file__).resolve().parent.parent
    for path in source.glob('*.py'):shutil.copyfile(path,resources/'Backend/dubbing'/path.name)
    for name in ['index.html','languages.json','requirements.txt','requirements-tested.txt']:
        shutil.copyfile(source/name,resources/'Backend/dubbing'/name)
    for name in ['__init__.py','bootstrap.py','service.py']:
        shutil.copyfile(source/'desktop'/name,resources/'Backend/dubbing/desktop'/name)
    tools={'uv':uv,'ffmpeg':media/'installed/bin/ffmpeg','ffprobe':media/'installed/bin/ffprobe'}
    for name,path in tools.items():
        dependencies=subprocess.check_output(['otool','-L',str(path)],text=True).splitlines()[1:]
        if any(not line.strip().startswith(('/usr/lib/','/System/Library/')) for line in dependencies):
            raise ValueError('Unbundled dynamic tool dependency: '+name)
        target=resources/'bin'/name;shutil.copyfile(path,target);target.chmod(0o755)
        subprocess.run(['codesign','--force','--sign','-',str(target)],check=True)
    notices=resources/'Notices'
    for name in ['LICENSE','THIRD_PARTY_NOTICES.md']:
        shutil.copyfile(source.parent/name,notices/name)
    for name in ['COPYING.LGPLv2.1','LICENSE.md']:
        shutil.copyfile(media/'ffmpeg-9.0.2'/name,notices/('FFmpeg-'+name))
    for name in ['COPYING','LICENSE']:
        shutil.copyfile(media/'lame-4.0'/name,notices/('LAME-'+name))
    for name in ['LICENSE-MIT','LICENSE-APACHE']:
        with urllib.request.urlopen('https://raw.githubusercontent.com/astral-sh/uv/'+UV_VERSION+'/'+name,timeout=30) as response:
            (notices/('uv-'+name)).write_bytes(response.read())
    for path in (media/'sources').iterdir():
        if path.is_file() and not path.name.endswith('.part'):shutil.copyfile(path,notices/'Source'/path.name)
    shutil.copyfile(source/'desktop/build_media.py',notices/'Source/build_media.py')
    (notices/'Third-party-tools.txt').write_text('FFmpeg 9.0.2: https://ffmpeg.org/ (LGPL 2.1+). LAME 4.0: https://lame.sourceforge.io/ (LGPL 2). uv 0.11.19: https://github.com/astral-sh/uv (MIT or Apache 2). Original licenses and corresponding media-tool sources/build instructions are included. Tools communicate with the application as separate processes. Downloaded Python packages/models retain their respective licenses in their installed distributions/model caches.\n')
    iconset=output/'LocalDub.iconset'
    subprocess.run(['xcrun','swift','-module-cache-path',str(module_cache),str(source/'desktop/render_icon.swift'),str(iconset)],check=True)
    subprocess.run(['iconutil','-c','icns',str(iconset),'-o',str(resources/'LocalDub.icns')],check=True)
    info={'CFBundleExecutable':'PodcastDubbing','CFBundleIdentifier':'app.localdub.desktop','CFBundleName':'LocalDub','CFBundleDisplayName':'LocalDub','CFBundlePackageType':'APPL','CFBundleShortVersionString':VERSION,'CFBundleVersion':'1','CFBundleIconFile':'LocalDub.icns','LSApplicationCategoryType':'public.app-category.music','LSMinimumSystemVersion':'26.0','NSHighResolutionCapable':True,'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}}
    (contents/'Info.plist').write_bytes(plistlib.dumps(info))
    sdk=subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()
    subprocess.run(['xcrun','swiftc','-parse-as-library','-swift-version','5','-O','-target','arm64-apple-macosx26.0','-sdk',sdk,'-module-cache-path',str(module_cache),'-o',str(contents/'MacOS/PodcastDubbing'),str(source/'desktop/App.swift')],check=True)
    manifest={str(path.relative_to(resources)):digest(path) for path in sorted(resources.rglob('*')) if path.is_file()}
    (resources/'bundle-manifest.json').write_text(json.dumps({'version':VERSION,'architecture':'arm64','minimum_macos':'26.0','uv_version':UV_VERSION,'source_uv_sha256':digest(uv),'files':manifest},indent=2))
    subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
    (output/'Install.txt').write_text(f'LocalDub {VERSION}\n\nRequires Apple Silicon and macOS 26 or later. Copy LocalDub.app to Applications, then open it. First launch downloads Python, packages and approximately 8 GB of models; allow 25 GB free for setup and working files. No Homebrew or Python installation is required. Model inference stays local.\n\nThis development build is ad-hoc signed and not notarized; macOS may require an explicit Open action. No Gatekeeper settings are changed.\n')
    archive=output/f'LocalDub-{VERSION}-arm64.zip'
    subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(app),str(archive)],check=True)
    print(json.dumps({'app':str(app),'archive':str(archive),'sha256':digest(archive),'signing':'ad-hoc; not notarized'},indent=2),flush=True)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--media-root',type=Path,required=True);parser.add_argument('--uv',type=Path,required=True);parser.add_argument('--module-cache',type=Path,required=True)
    args=parser.parse_args();build(args.output,args.media_root,args.uv,args.module_cache)
