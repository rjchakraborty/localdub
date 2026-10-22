"""Bundled, local voice cleanup plugin. No models or network access required."""
import math
from pathlib import Path

import numpy as np
import soundfile as sf

from .audio import command
from .preprocessing import digest

VERSION = '1.0.0'
PRESETS = {'gentle': (60, 6), 'balanced': (70, 10), 'strong': (80, 16)}


def measure(path):
    info = sf.info(path)
    if info.samplerate != 24000 or info.channels != 1 or not info.frames:
        raise ValueError('Voice cleanup requires nonempty mono 24 kHz audio')
    peak, energy, frames = 0.0, 0.0, 0
    for block in sf.blocks(path, blocksize=240000, dtype='float32'):
        if not np.isfinite(block).all():
            raise ValueError('Voice cleanup received invalid samples')
        peak = max(peak, float(np.max(np.abs(block))))
        energy += float(np.sum(block.astype(np.float64) ** 2))
        frames += len(block)
    return {'frames': frames, 'sample_rate': info.samplerate, 'peak': peak, 'rms': math.sqrt(energy / frames)}


def process(source: Path, destination: Path, strength='gentle'):
    """Reduce stationary noise/rumble, then apply bounded constant gain.

    Never gate, trim silence, compress dynamics, or reconstruct missing speech.
    Partial output is discarded; a prior destination survives a failed attempt.
    """
    cutoff, reduction = PRESETS[strength]
    before = measure(source)
    filtered = destination.with_name('.cleanup-filtered.wav')
    partial = destination.with_name('.cleanup-output.wav')
    # afftdn's three-hop window delays output by two 1/80-second hops.
    # Flush the tail, then discard that latency without shifting speech timing.
    latency = 2 * (before['sample_rate'] // 80)
    filters = f'apad=pad_len={latency},highpass=f={cutoff},afftdn=nr={reduction}:nf=-50:tn=1:gs=6'
    try:
        command(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(source),
                 '-af', filters, '-c:a', 'pcm_f32le', str(filtered)])
        cleaned = measure(filtered)
        if cleaned['frames'] != before['frames'] + latency:
            raise ValueError('Voice cleanup changed audio duration; processing stopped')
        if before['rms'] >= 1e-5 and cleaned['rms'] < 1e-5:
            raise ValueError('Voice cleanup removed too much signal; disable it or use a gentler setting')
        gain = 1.0
        if cleaned['rms'] >= 1e-5:
            gain = min(10 ** (6 / 20), 10 ** (-23 / 20) / cleaned['rms'], .95 / max(cleaned['peak'], 1e-12))
        with sf.SoundFile(partial, 'w', samplerate=24000, channels=1, subtype='PCM_16') as output:
            for block in sf.blocks(filtered, start=latency, frames=before['frames'], blocksize=240000, dtype='float32'):
                output.write(block * gain)
        after = measure(partial)
        receipt = {'plugin': 'voice_cleanup', 'enabled': True, 'version': VERSION,
                   'strength': strength, 'filters': filters, 'latency_compensation_frames': latency, 'gain_db': 20 * math.log10(gain),
                   'input_sha256': digest(source), 'output_sha256': digest(partial),
                   'before': before, 'after': after,
                   'limitations': ['Steady noise and rumble reduction; no speaker/music separation or de-reverberation.',
                                   'Filtering can alter voice texture; transcription improvement requires comparison.']}
        partial.replace(destination)
        return receipt
    finally:
        filtered.unlink(missing_ok=True)
        partial.unlink(missing_ok=True)
