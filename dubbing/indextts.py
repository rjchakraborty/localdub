"""Isolated IndexTTS 2.5 synthesis with source-audio emotion conditioning."""
import hashlib
import gc
import json
import math
import os
import re
from pathlib import Path
import sys
import subprocess
import time
import warnings

MODEL_REPO = 'vanch007/mlx-indextts2-2.5-8bit'
MODEL_REVISION = '3170ceff8032ab6d0c2945e72068a03ea8c68461'
RUNTIME_REVISION = 'a7666367b8551656a2029ad75f259cb5e4936b3b'


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    temporary.replace(path)


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle,'sha256').hexdigest()


def spoken_text(text,language):
    """Keep editorial punctuation from becoming narrated arithmetic or quotes."""
    if language=='zh':
        text=text.translate(str.maketrans('', '', '“”‘’「」『』'))
    def pause(match):
        before=text[match.start()-1:match.start()]
        after=text[match.end():match.end()+1]
        # Preserve actual numeric ranges and ordinary minus/hyphen characters.
        if before.isdigit() and after.isdigit():return match.group()
        return '，' if language=='zh' else ', '
    text=re.sub('[—–]+',pause,text)
    if language=='es':
        from dubbing.numbers import spanish_speech
        text=spanish_speech(text)
    return text


def short_utterance_fallback(row,language):
    return language=='zh' and row['end']-row['start']<1 and spoken_text(row['translation'],language).strip(' \t\r\n。.!?？！') in {'它','她','他'}


def reference_window(segment, duration=None):
    # Complete short thoughts retain their whole delivery; longer references use
    # an existing source boundary instead of silently truncating at 15 seconds.
    if duration is not None and segment['end']-segment['start']<1:
        start=max(0,segment['start']-2)
        return start,min(duration,start+5)
    if segment['end']-segment['start']<=15:
        return segment['start'],segment['end']
    return segment.get('reference_start',segment['start']),segment.get('reference_end',min(segment['end'],segment['start']+15))


def synthesize(folder):
    import numpy as np
    import soundfile as sf
    import torch
    import mlx.core as mx
    from scipy.signal import resample_poly
    from mlx_indextts import IndexTTSv25
    import mlx_indextts

    # MLX and PyTorch use separate Metal allocators on the same unified RAM.
    # Bound reusable MLX buffers and release unused PyTorch buffers before
    # synthesis; retained source features remain available on disk.
    mx.set_cache_limit(512 * 1024**2)

    runtime_root=Path(mlx_indextts.__file__).resolve().parent.parent
    runtime_revision=subprocess.check_output(['git','-C',str(runtime_root),'rev-parse','HEAD'],text=True).strip()
    if runtime_revision!=RUNTIME_REVISION:raise RuntimeError('IndexTTS runtime revision changed; review it before rendering')

    model_dir=Path(os.environ['DUBBING_INDEXTTS_MODEL']).resolve()
    if model_dir.name!=MODEL_REVISION or model_dir.parent.name!='snapshots':
        raise RuntimeError('IndexTTS model must be the pinned, reviewed snapshot')
    if str(read(model_dir/'model_manifest.json')['model_version'])!='2.5':
        raise RuntimeError('Expected IndexTTS 2.5 model manifest')
    camp_path=Path(os.environ['DUBBING_INDEXTTS_CAMPPLUS'])
    if not camp_path.is_file():
        raise RuntimeError('Verified CAMPPlus speaker weights are required')

    class VerifiedIndexTTS(IndexTTSv25):
        exhausted=False

        def _ensure_pytorch_modules(self):
            if self._preprocessing_initialized:return
            super()._ensure_pytorch_modules()
            # The upstream port can silently use a random speaker encoder after
            # a load error. Require a strict real checkpoint load before use.
            weights=torch.load(str(camp_path),map_location='cpu',weights_only=True)
            self.campplus.load_state_dict(weights,strict=True)

        def _generate_semantic_codes(self,*args,**kwargs):
            # The port compresses repeated silence before returning codes, so
            # returned length alone cannot reliably detect budget exhaustion.
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always',RuntimeWarning)
                codes=super()._generate_semantic_codes(*args,**kwargs)
            for warning in caught:
                if 'generation reached max_mel_tokens=' in str(warning.message):
                    self.exhausted=True
                else:
                    warnings.warn(str(warning.message),warning.category)
            return codes

    job=read(folder/'job.json');options=job['options']
    rows=read(folder/'translation.json')
    wave,sr=sf.read(folder/'source.wav',dtype='float32')
    if sr!=24000 or wave.ndim!=1:raise ValueError('Expected normalized mono 24kHz source')
    target=folder/'segments';target.mkdir(exist_ok=True)
    source_hash=digest(folder/'source.wav')
    configuration={'engine':'IndexTTS 2.5','model':MODEL_REPO,'model_revision':MODEL_REVISION,'runtime_revision':RUNTIME_REVISION,'renderer_sha256':digest(Path(__file__)),'reference_mode':options.get('reference_mode','passage'),'emotion_strength':options.get('emotion_strength',.8),'emotion_source':'original passage audio','native_sample_rate':22050,'storage_sample_rate':24000,'diffusion_steps':25,'duration_factor':1.0,'pitch_shift':False,'limitation':'Source emotion conditioning approximates performance. Stable mode assumes one primary narrator; no diarization, internal semantic pause mapping or background-stem separation.'}
    save(folder/'voice-configuration.json',configuration)
    text_tokens=options.get('indextts_text_tokens',40)
    if not isinstance(text_tokens,int) or not 20<=text_tokens<=40:
        raise ValueError('IndexTTS text chunks must contain 20 to 40 tokens')
    configuration.update(max_text_tokens_per_segment=text_tokens,conditioning_version=2)
    configuration.update(mlx_cache_limit_bytes=512*1024**2,release_unused_metal_buffers=True)
    configuration['spoken_text_normalization']=1
    if options['language']=='es':
        from dubbing import numbers
        configuration.update(spoken_text_normalization=2,number_normalizer_sha256=digest(Path(numbers.__file__)),number_normalizer='num2words 0.5.14 Spanish; deterministic numeric punctuation')
    configuration['short_utterance_fallback']='Qwen3-TTS balanced reference voice; explicitly reported per passage'
    save(folder/'voice-configuration.json',configuration)
    model=None
    reference_cache=Path(os.environ['DUBBING_HOME'])/'voice-reference-cache'/'indextts25-bounded'
    reference_cache.mkdir(parents=True,exist_ok=True)
    repairs=read(folder/'synthesis-repairs.json') if (folder/'synthesis-repairs.json').exists() else []

    def excerpt(path,start,end):
        if not 0<=start<end<=len(wave)/sr+.01 or end-start>15.01:
            raise ValueError('Voice reference must be a real source interval up to 15 seconds')
        sf.write(path,wave[round(start*sr):round(end*sr)],sr,subtype='PCM_16')

    def cached_reference(path):
        key=hashlib.sha256((digest(path)+MODEL_REVISION+RUNTIME_REVISION).encode()).hexdigest()
        cached=reference_cache/(key+'.npz')
        if not cached.exists():model.save_speaker(str(path),str(cached))
        return cached

    stable_path=target/'identity-reference.wav'
    stable_interval=None
    if configuration['reference_mode']=='stable':
        passages=read(folder/'transcript.json')['segments']
        candidates=[s for s in passages if s['start']<120 and 5<=s['end']-s['start']<=15]
        if not candidates:raise ValueError('No suitable narration reference; use passage reference mode')
        chosen=max(candidates,key=lambda s:s['end']-s['start'])
        stable_interval=[chosen['start'],chosen['end']]
        excerpt(stable_path,*stable_interval)
        configuration.update(identity_reference_interval=stable_interval,identity_reference_sha256=digest(stable_path))
        save(folder/'voice-configuration.json',configuration)

    for index,row in enumerate(rows):
        if (folder/'cancel').exists():raise InterruptedError('Cancelled; completed passages retained')
        save(folder/'progress.json',{'stage':'synthesis','completed':index,'total':len(rows),'updated':time.time()})
        if short_utterance_fallback(row,options['language']):
            print(json.dumps({'passage':index,'deferred_to':'qwen_short_utterance_fallback'}),flush=True)
            continue
        repair_count=sum(index in e['segments'] for e in repairs)
        start,end=reference_window(row,len(wave)/sr)
        ref=target/f"reference-{row['id']:05}.wav"
        excerpt(ref,start,end)
        identity=stable_path if stable_interval else ref
        fingerprint=hashlib.sha256(json.dumps({'row':row,'source':source_hash,'configuration':configuration,'identity':digest(identity),'emotion':digest(ref),'seed':options.get('seed',42),'temperature':options.get('temperature',.6),'repairs':repair_count},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        output=target/f"{row['id']:05}.wav";receipt=output.with_suffix('.json')
        if output.exists() and receipt.exists() and read(receipt).get('input_sha256')==fingerprint and read(receipt).get('audio_sha256')==digest(output):continue
        if output.exists():
            stale=target/f"{row['id']:05}-{time.time_ns()}-stale.wav";output.replace(stale)
            if receipt.exists():receipt.replace(stale.with_suffix('.json'))
        duration_limit=max(12,4*(row['end']-row['start']))
        minimum=max(.2,len(''.join(row['translation'].split()))/(10 if options['language']=='zh' else 32))
        if model is None:model=VerifiedIndexTTS(str(model_dir),memory_limit_gb=8)
        identity_cache=cached_reference(identity)
        emotion_cache=cached_reference(ref)
        if torch.backends.mps.is_available():
            torch.mps.synchronize()
            torch.mps.empty_cache()
        accepted=False
        for attempt in range(options.get('synthesis_retries',2)+1):
            seed=options.get('seed',42)+index+attempt*1009+repair_count*3001
            model.exhausted=False
            begun=time.monotonic()
            audio=model.generate(text=spoken_text(row['translation'],options['language']),reference_audio=str(identity_cache),emotion_reference_audio=str(emotion_cache),language=options['language'],emo_alpha=configuration['emotion_strength'],seed=seed,temperature=options.get('temperature',.6),max_mel_tokens=min(1500,math.ceil(duration_limit*25)),max_text_tokens_per_segment=text_tokens,diffusion_steps=25,repetition_penalty=10.,interval_silence=200,verbose=False)
            audio=np.asarray(audio,dtype=np.float32).reshape(-1)
            valid=len(audio) and np.isfinite(audio).all() and minimum<=len(audio)/22050<=duration_limit and np.max(np.abs(audio))>=.001 and not model.exhausted
            if valid:accepted=True;break
            if len(audio) and np.isfinite(audio).all():sf.write(target/f"{row['id']:05}-{time.time_ns()}-rejected.wav",audio,22050)
        if not accepted:raise ValueError(f'IndexTTS failed bounded validation at passage {index}')
        audio=resample_poly(audio,160,147)
        peak=float(np.max(np.abs(audio)))
        if peak>.98:audio*=.98/peak
        temporary=output.with_suffix('.part.wav');sf.write(temporary,audio,24000,subtype='PCM_16');temporary.replace(output)
        save(receipt,{'engine':'indextts25','model':MODEL_REPO,'seed':seed,'attempt':attempt,'conditioning':'source_emotion_and_voice','input_sha256':fingerprint,'audio_sha256':digest(output),'reference_interval':[start,end],'identity_interval':stable_interval,'emotion_strength':configuration['emotion_strength'],'generation_seconds':time.monotonic()-begun,'generation':model.last_generation_info,'spoken_text':spoken_text(row['translation'],options['language']),'generation_renderer_sha256':configuration['renderer_sha256']})
        model._reference_cache.clear()
        model.cache={}
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.synchronize()
            torch.mps.empty_cache()
        mx.clear_cache()
        memory={'mlx_active_bytes':mx.get_active_memory(),'mlx_cached_bytes':mx.get_cache_memory()}
        if torch.backends.mps.is_available():
            memory.update(torch_mps_active_bytes=torch.mps.current_allocated_memory(),torch_mps_driver_bytes=torch.mps.driver_allocated_memory())
        print(json.dumps({'memory_after_passage':index,**memory}),flush=True)
        print(json.dumps({'passage':index,'total':len(rows),'seconds':len(audio)/24000,'attempt':attempt}),flush=True)
    save(folder/'progress.json',{'stage':'synthesis','completed':len(rows),'total':len(rows),'updated':time.time()})


if __name__=='__main__':
    synthesize(Path(sys.argv[1]))
