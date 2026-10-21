"""Build self-contained audio tools from checksum-pinned upstream sources."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request

SOURCES={
    'ffmpeg':('9.0.2','https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz','8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e'),
    'lame':('4.0','https://downloads.sourceforge.net/project/lame/lame/4.0/lame-4.0.tar.gz','3df5124d5ad3a98312ffd7ba6a9b36230e4f8a3e66d3ce0f425e336c32d216eb'),
}


def command(args,cwd,env):
    print('RUN',*map(str,args),flush=True)
    subprocess.run(list(map(str,args)),cwd=cwd,env=env,check=True)


def build(root):
    root=root.resolve();root.mkdir(parents=True,exist_ok=True)
    sources=root/'sources';sources.mkdir(exist_ok=True)
    for name,(version,url,expected) in SOURCES.items():
        archive=sources/url.rsplit('/',1)[1]
        if not archive.exists():
            partial=archive.with_suffix('.part')
            with urllib.request.urlopen(url,timeout=60) as response,partial.open('wb') as output:
                while data:=response.read(1024*1024):output.write(data)
            partial.replace(archive)
        with archive.open('rb') as handle:actual=hashlib.file_digest(handle,'sha256').hexdigest()
        if actual!=expected:raise ValueError('Source checksum mismatch: '+name)
        if not (root/f'{name}-{version}').is_dir():
            with tarfile.open(archive) as package:package.extractall(root,filter='data')
    prefix=root/'lame-static';env={**os.environ,'MACOSX_DEPLOYMENT_TARGET':'26.0'}
    env['CFLAGS']='-O2 -mmacosx-version-min=26.0'
    env['LDFLAGS']='-mmacosx-version-min=26.0'
    env['PKG_CONFIG_LIBDIR']=str(prefix/'lib/pkgconfig')
    lame=root/'lame-4.0'
    if not (prefix/'.encoder-only').exists():
        command(['./configure','--prefix='+str(prefix),'--enable-static','--disable-shared','--disable-frontend','--disable-decoder','--disable-dependency-tracking'],lame,env)
        command(['make','clean'],lame,env)
        command(['make','-j2'],lame,env);command(['make','install'],lame,env)
        (prefix/'.encoder-only').write_text('LAME4.0 encoder only; decoder deliberately disabled\n')
    ffmpeg=root/'ffmpeg-9.0.2';destination=root/'installed'
    env['PKG_CONFIG_LIBDIR']=str(prefix/'lib/pkgconfig')
    binary=destination/'bin/ffmpeg'
    formats=subprocess.check_output([str(binary),'-hide_banner','-muxers'],text=True) if binary.exists() else ''
    if not all(name in formats.split() for name in ['s16le','f32le','wav','mp3']):
        command(['./configure','--prefix='+str(destination),'--disable-everything','--disable-autodetect','--disable-network','--disable-doc','--disable-debug','--disable-shared','--enable-static','--enable-ffmpeg','--enable-ffprobe','--disable-ffplay','--enable-libmp3lame',
            '--extra-cflags=-I'+str(prefix/'include')+' -mmacosx-version-min=26.0',
            '--extra-ldflags=-L'+str(prefix/'lib')+' -mmacosx-version-min=26.0',
            '--enable-protocol=file,pipe',
            '--enable-decoder=mp3,mp3float,aac,aac_fixed,flac,vorbis,opus,alac,ac3,eac3,ape,wavpack,wmav1,wmav2,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le,pcm_s16be,pcm_s24be,pcm_s32be,pcm_f32be,pcm_u8,pcm_alaw,pcm_mulaw,adpcm_ima_wav,adpcm_ms',
            '--enable-parser=mpegaudio,aac,aac_latm,flac,vorbis,opus,ac3',
            '--enable-demuxer=mp3,wav,aiff,flac,ogg,mov,aac,matroska,asf,au,ape,wv,ac3,eac3',
            '--enable-encoder=pcm_s16le,pcm_f32le,libmp3lame','--enable-muxer=wav,mp3,pcm_s16le,pcm_f32le',
            '--enable-filter=abuffer,abuffersink,aresample,atempo,anull,asetpts'],ffmpeg,env)
        command(['make','-j2'],ffmpeg,env);command(['make','install'],ffmpeg,env)
    formats=subprocess.check_output([str(binary),'-hide_banner','-muxers'],text=True)
    if not all(name in formats.split() for name in ['s16le','f32le','wav','mp3']):
        raise ValueError('Built audio tool is missing a required PCM or export format')
    for name in ['ffmpeg','ffprobe']:
        binary=destination/'bin'/name
        linked=subprocess.check_output(['otool','-L',str(binary)],text=True)
        dependencies=[line.strip().split(' (',1)[0] for line in linked.splitlines()[1:]]
        if any(not name.startswith(('/usr/lib/','/System/Library/')) for name in dependencies):
            raise ValueError('Audio tool has external dynamic dependencies: '+str(dependencies))
        print(linked,flush=True)
    return destination


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--build-root',type=Path,required=True)
    print(build(parser.parse_args().build_root),flush=True)
