"""Lazy audio plugin boundary; disabled plugins never execute."""
from importlib import import_module
import hashlib
from pathlib import Path
import shutil


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare_audio(source, destination, options):
    if not options.audio_enhancement:
        shutil.copyfile(source, destination)
        return {'plugin': 'voice_cleanup', 'enabled': False, 'output_sha256': digest(destination)}
    try:
        plugin = import_module('dubbing.audio_enhancement')
    except ModuleNotFoundError as exc:
        if exc.name != 'dubbing.audio_enhancement':
            raise
        raise RuntimeError('Voice cleanup plugin is unavailable. Disable Voice cleanup or reinstall LocalDub.') from exc
    return plugin.process(source, destination, options.enhancement_strength)
