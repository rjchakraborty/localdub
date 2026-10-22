import json
import math
import subprocess
from contextlib import ExitStack
from pathlib import Path

import numpy as np
import soundfile as sf

INPUT_FORMATS="mp3,wav,flac,ogg,mov,aac,aiff,matroska,webm,asf,au,ape,wv,ac3,eac3"


def command(args: list[str], timeout=900):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr[-1800:]}")
    return result.stdout


def probe(path: Path) -> dict:
    with path.open('rb') as stream:
        header=stream.read(4096).removeprefix(b'\xef\xbb\xbf').lstrip()
    if header.startswith((b'#EXTM3U',b'[playlist]')):
        raise ValueError('Use a standalone audio file; playlists and external references are not supported.')
    try:
        data = json.loads(command(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-format_whitelist",INPUT_FORMATS, "-show_format", "-show_streams", "-of", "json", str(path)]))
    except RuntimeError as exc:
        if 'not on whitelist' in str(exc):
            raise ValueError('Use a standalone audio file such as MP3, WAV, M4A, FLAC or OGG. Playlists and external references are not supported.') from exc
        if 'Invalid data found' in str(exc):
            raise ValueError('Input is not readable standalone audio. Use an audio file or a specific supported podcast episode URL.') from exc
        raise
    if not any(s.get("codec_type") == "audio" for s in data.get("streams", [])):
        raise ValueError("Input has no audio stream")
    duration = float(data["format"]["duration"])
    if not math.isfinite(duration) or not 0.5 <= duration <= 7200:
        raise ValueError("Audio must be between 0.5 seconds and 2 hours")
    return {"duration": duration, "streams": data["streams"]}


def normalize(source: Path, dest: Path):
    command(["ffmpeg", "-nostdin", "-v", "error", "-y", "-protocol_whitelist", "file,pipe", "-format_whitelist",INPUT_FORMATS, "-i", str(source), "-vn", "-ac", "1", "-ar", "24000", str(dest)])


def source_signal(path: Path):
    peak, energy, frames = 0.0, 0.0, 0
    for block in sf.blocks(path, blocksize=24000, dtype="float32"):
        if not np.isfinite(block).all():
            raise ValueError("Source contains invalid audio samples")
        peak = max(peak, float(np.max(np.abs(block))))
        energy += float(np.sum(block.astype(np.float64)**2))
        frames += len(block)
    rms = math.sqrt(energy/max(1, frames))
    if peak < .0001 or rms < .00001:
        raise ValueError("Source audio is silent or too quiet for reliable speech recognition")
    return {"peak": peak, "rms": rms}


def segments_from_words(segments: list, duration: float, max_seconds=15, pause=0.65):
    words = [w for s in segments for w in s.get("words", []) if w.get("word", "").strip()]
    result, current = [], []
    for word in words:
        start, end = float(word["start"]), float(word["end"])
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration + 0.1):
            continue
        if current and (start - current[-1]["end"] >= pause or end - current[0]["start"] > max_seconds):
            result.append({"start": current[0]["start"], "end": current[-1]["end"], "text": "".join(w["word"] for w in current).strip()})
            current = []
        current.append({"start": start, "end": min(end, duration), "word": word["word"]})
        if end - current[0]["start"] >= 5 and word["word"].rstrip().endswith((".", "?", "!", "。")):
            result.append({"start": current[0]["start"], "end": current[-1]["end"], "text": "".join(w["word"] for w in current).strip()})
            current = []
    if current:
        result.append({"start": current[0]["start"], "end": current[-1]["end"], "text": "".join(w["word"] for w in current).strip()})
    if not result:
        raise ValueError("No timed speech detected; silent/music-only input cannot be dubbed")
    for i, segment in enumerate(result):
        segment["id"] = i
    return result


def timestamp(seconds):
    millis = round(seconds * 1000)
    return f"{millis // 3600000:02}:{millis // 60000 % 60:02}:{millis // 1000 % 60:02}.{millis % 1000:03}"


def ambient_without_speech(audio, sample_rate=24000):
    """Preserve gap ambience while masking speech-like frames with guard margins."""
    import webrtcvad
    from scipy.signal import resample_poly

    if not len(audio):
        return audio, 0
    resampled = resample_poly(audio,2,3)
    pcm = (np.clip(resampled,-1,1)*32767).astype("<i2")
    vad = webrtcvad.Vad(2)
    mask = np.ones(len(audio),dtype=np.float32)
    frame_size = 320  # 20ms at 16kHz
    for start in range(0,len(pcm),frame_size):
        frame = pcm[start:start+frame_size]
        if len(frame)<frame_size:
            frame = np.pad(frame,(0,frame_size-len(frame)))
        if vad.is_speech(frame.tobytes(),16000):
            left = max(0,round(start*sample_rate/16000)-2400)
            right = min(len(audio),round((start+frame_size)*sample_rate/16000)+2400)
            mask[left:right] = 0
    return audio*mask,float(np.sum(mask==0))/sample_rate


class AssemblyBuffer:
    """Spool float samples to disk instead of retaining a complete podcast twice."""
    def __init__(self, folder):
        self.folder = folder
        self.path = folder / '.assembly-float.wav'
        self.pcm = folder / '.assembly-pcm.wav'
        self.peak = 0.0
        self.frames = 0

    def __enter__(self):
        self.writer = sf.SoundFile(self.path, 'w', samplerate=24000, channels=1, subtype='FLOAT')
        return self

    def append(self, audio):
        if len(audio):
            self.peak = max(self.peak, float(np.max(np.abs(audio))))
            self.writer.write(audio)
            self.frames += len(audio)

    def finish(self):
        self.writer.close()
        if self.peak < .001:
            raise ValueError('Generated output is effectively silent')
        scale = .98 / self.peak if self.peak > .98 else 1.0
        with sf.SoundFile(self.pcm, 'w', samplerate=24000, channels=1, subtype='PCM_16') as output:
            for block in sf.blocks(self.path, blocksize=240000, dtype='float32'):
                if scale != 1.0:
                    block *= scale
                output.write(block)
        self.pcm.replace(self.folder / 'dubbed.wav')

    def __exit__(self, *exc):
        self.writer.close()
        self.path.unlink(missing_ok=True)
        self.pcm.unlink(missing_ok=True)


def assemble(folder: Path, segments: list, options, duration: float):
    with ExitStack() as stack:
        buffer = stack.enter_context(AssemblyBuffer(folder))
        reference = folder / 'source-original.wav'
        if not reference.exists():
            reference = folder / 'source.wav'
        original = stack.enter_context(sf.SoundFile(reference)) if options.gap_audio != 'silence' else None
        return _assemble(folder, segments, options, duration, buffer, original)


def _assemble(folder, segments, options, duration, pieces, original):
    sample_rate = 24000
    cues, warnings = [], []
    masked_gap_seconds = 0.0
    if original is not None:
        if original.samplerate != sample_rate or original.channels != 1:
            raise ValueError("Gap reference must be mono 24kHz audio")

    def gap_piece(start, seconds):
        nonlocal masked_gap_seconds
        count = round(seconds * sample_rate)
        if original is None:
            return np.zeros(count, dtype=np.float32)
        original.seek(min(round(start*sample_rate), len(original)))
        excerpt = original.read(count, dtype='float32')
        excerpt = np.pad(excerpt, (0, max(0, count-len(excerpt))))[:count]
        if options.gap_audio=="ambient":
            excerpt,masked = ambient_without_speech(excerpt,sample_rate)
            masked_gap_seconds += masked
        return excerpt
    cursor, previous_end = 0.0, 0.0
    for segment in segments:
        audio, sr = sf.read(folder / "segments" / f"{segment['id']:05}.wav", dtype="float32")
        if sr != sample_rate or audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():
            raise ValueError(f"Invalid synthesis for segment {segment['id']}")
        target = segment["end"] - segment["start"]
        generated = len(audio) / sr
        if options.timing == "aligned" and generated > target:
            ratio = generated / target
            if ratio > options.max_speedup:
                warnings.append(f"Segment {segment['id']} extends timing; needed speedup {ratio:.2f} exceeds limit")
            speed = min(ratio, options.max_speedup)
            adjusted = folder / "segments" / f"{segment['id']:05}-timed.wav"
            command(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(folder / "segments" / f"{segment['id']:05}.wav"), "-af", f"atempo={speed}", str(adjusted)])
            audio, _ = sf.read(adjusted, dtype="float32")
        gap = max(0, segment["start"] - previous_end)
        if options.timing == "aligned":
            gap = max(0, segment["start"] - cursor)
        if gap:
            pieces.append(gap_piece(previous_end, gap))
            cursor += gap
        start = cursor
        # Tiny fades avoid discontinuities without removing speech.
        fade = min(120, len(audio) // 4)
        audio[:fade] *= np.linspace(0, 1, fade)
        audio[-fade:] *= np.linspace(1, 0, fade)
        pieces.append(audio)
        cursor += len(audio) / sr
        cues.append({**segment, "output_start": start, "output_end": cursor})
        if options.timing == "aligned" and cursor < segment["end"]:
            pieces.append(np.zeros(round((segment["end"] - cursor) * sr), dtype=np.float32))
            cursor = segment["end"]
        previous_end = segment["end"]
    trailing = max(0, duration - previous_end) if options.timing == "natural" else max(0, duration - cursor)
    pieces.append(gap_piece(previous_end, trailing))
    peak = pieces.peak
    pieces.finish()
    command(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(folder / "dubbed.wav"), "-codec:a", "libmp3lame", "-b:a", "128k", str(folder / "dubbed.mp3")])
    vtt = "WEBVTT\n\n" + "\n\n".join(f"{timestamp(s['output_start'])} --> {timestamp(s['output_end'])}\n{s['translation']}" for s in cues) + "\n"
    (folder / "translated.vtt").write_text(vtt)
    return {"segments": len(cues), "duration": pieces.frames / sample_rate, "peak_before_normalization": peak, "masked_gap_seconds":masked_gap_seconds, "warnings": warnings, "timeline": cues}
