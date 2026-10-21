"""Read back assembled speech; this does not measure emotional fidelity."""
import json
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import soundfile as sf
from opencc import OpenCC

from .pipeline import read, save
from .numbers import numeric_readback

_SIMPLIFY = OpenCC("t2s")


def canonical(text):
    text = _SIMPLIFY.convert(text)
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if c.isalnum())


def speech_scores(expected,actual,language):
    expected,actual=canonical(expected),canonical(actual)
    strict=SequenceMatcher(None,expected,actual,autojunk=False).ratio()
    if language=='zh':
        # These written pronouns have identical Mandarin pronunciation (tā).
        # Keep the orthographic score too; this does not equate their meanings.
        pronouns=str.maketrans({'她':'他','它':'他'})
        expected,actual=expected.translate(pronouns),actual.translate(pronouns)
    return strict,SequenceMatcher(None,expected,actual,autojunk=False).ratio()


def compare_readbacks(expected,full,language,isolated=None):
    strict,score=speech_scores(expected,full,language)
    result={'recognized':full,'text_similarity':score,'strict_text_similarity':strict,'pronoun_homophone_adjustment':strict!=score,'comparison_basis':'full_assembled_readback','full_recognized':full,'full_text_similarity':score,'full_strict_text_similarity':strict}
    full_numbers=numeric_readback(expected,full,language)
    result.update(numeric_check=full_numbers,full_numeric_check=full_numbers)
    if isolated is not None:
        isolated_strict,isolated_score=speech_scores(expected,isolated,language)
        result['isolated_readback']={'recognized':isolated,'text_similarity':isolated_score,'strict_text_similarity':isolated_strict,'expected_text_prompt':False}
        isolated_numbers=numeric_readback(expected,isolated,language)
        result['isolated_readback']['numeric_check']=isolated_numbers
        # A high character score must not override an incorrect count or year.
        if (isolated_numbers['status']!='review_required',isolated_score)>(full_numbers['status']!='review_required',score):
            result.update(recognized=isolated,text_similarity=isolated_score,strict_text_similarity=isolated_strict,pronoun_homophone_adjustment=isolated_score!=isolated_strict,comparison_basis='isolated_assembled_passage',numeric_check=isolated_numbers)
    return result


def passage_passed(result):
    return result['text_similarity']>=.75 and result['clipped_fraction']<.01 and result['rms']>.001 and result.get('numeric_check',{}).get('status')!='review_required'


def assembled_excerpt(folder,cue):
    from scipy.signal import resample_poly

    path=folder/'dubbed.wav'
    rate=sf.info(path).samplerate
    wave,rate=sf.read(path,start=round(cue['output_start']*rate),stop=round(cue['output_end']*rate),dtype='float32')
    if rate!=24000 or wave.ndim!=1 or not len(wave):
        raise ValueError('Invalid assembled passage for independent speech recheck')
    return resample_poly(wave,2,3).astype(np.float32)


def align_readback(words,timeline):
    aligned = [[] for _ in timeline]
    gaps = []
    for word in words:
        midpoint = (word["start"]+word["end"])/2
        index = min(range(len(timeline)),key=lambda i:max(timeline[i]["output_start"]-midpoint,midpoint-timeline[i]["output_end"],0))
        cue = timeline[index]
        if cue["output_start"]-.2 <= midpoint <= cue["output_end"]+.2:
            aligned[index].append(word["word"])
        else:
            gaps.append(word)
    return ["".join(w) for w in aligned],gaps


def audit(folder: Path):
    import mlx_whisper
    from .models import model_path
    from .settings import ASR_MODEL

    segments = read(folder / "translation.json")
    options = read(folder / "job.json")["options"]
    timeline = read(folder/"report.json")["timeline"]
    readback = mlx_whisper.transcribe(str(folder/"dubbed.wav"),path_or_hf_repo=model_path(ASR_MODEL),language=options["language"],word_timestamps=True,verbose=False,temperature=0,condition_on_previous_text=False)
    save(folder/"readback.json",readback)
    words = [w for s in readback["segments"] for w in s.get("words",[])]
    recognized,gap_words = align_readback(words,timeline)
    results = []
    for index in range(len(segments)):
        segment = segments[index]
        audio = folder / "segments" / f"{segment['id']:05}.wav"
        comparison=compare_readbacks(segment['translation'],recognized[index],options['language'])
        if comparison['text_similarity']<.75 or comparison['numeric_check']['status']=='review_required':
            # Recheck the actual rendered output crop, without expected-text hints.
            isolated=mlx_whisper.transcribe(assembled_excerpt(folder,timeline[index]),path_or_hf_repo=model_path(ASR_MODEL),language=options['language'],verbose=False,temperature=0,condition_on_previous_text=False)
            comparison=compare_readbacks(segment['translation'],recognized[index],options['language'],isolated['text'])
            comparison['isolated_readback'].update(output_start=timeline[index]['output_start'],output_end=timeline[index]['output_end'])
        wave, sr = sf.read(audio)
        results.append({"segment": index, "expected": segment["translation"],**comparison, "duration": len(wave)/sr, "clipped_fraction": float(np.mean(np.abs(wave)>=0.999)), "rms": float(np.sqrt(np.mean(wave**2)))})
    passed = all(passage_passed(r) for r in results)
    combined_strict,combined_similarity=speech_scores(' '.join(s['translation'] for s in segments),readback['text'],options['language'])
    report = {"scope": "Assembled audio, timestamp-aligned to every generated passage", "checks": len(results), "passed": sum(passage_passed(r) for r in results), "minimum_text_similarity":0.75, "combined_text_similarity":combined_similarity,"unassigned_gap_words":gap_words,"status": "speech_checks_passed" if passed else "listening_review_required", "samples": results, "limitation": "ASR similarity and approximate timestamp alignment are intelligibility screens, not proof of translation accuracy, voice identity or preserved emotion"}
    report.update(combined_strict_text_similarity=combined_strict,normalization='Traditional/Simplified Chinese, punctuation/case/diacritics; Mandarin pronouns 他/她/它 compare as the same spoken syllable. Strict orthographic scores are retained.',audit_version=3,isolated_rechecks=sum('isolated_readback' in s for s in results),comparison_note='Low full-file scores are corroborated on the actual assembled passage without expected-text prompts. Both recognitions and scores are retained; higher agreement selects the speech-screen result, not a semantic verdict.')
    report.update(audit_version=4,numeric_review_required=sum(r['numeric_check']['status']=='review_required' for r in results))
    save(folder / "audit.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    import sys
    audit(Path(sys.argv[1]))
