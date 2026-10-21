"""Timing and validation invariants, using real audio files and ffmpeg."""
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from pydantic import ValidationError

from dubbing.audio import assemble, normalize, probe, segments_from_words, timestamp, source_signal
from dubbing.settings import Options
from dubbing.sources import public_url


def test_streamed_assembly_preserves_global_peak_normalization(tmp_path):
    from dubbing.audio import AssemblyBuffer
    samples=np.concatenate([np.linspace(-1.25,.5,240037,dtype=np.float32),np.ones(300003,dtype=np.float32)*.2])
    with AssemblyBuffer(tmp_path) as buffer:
        buffer.append(samples[:17000]);buffer.append(samples[17000:])
        buffer.finish()
    expected=samples.copy();expected*=.98/float(np.max(np.abs(expected)))
    sf.write(tmp_path/'reference.wav',expected,24000,subtype='PCM_16')
    assert (tmp_path/'dubbed.wav').read_bytes()==(tmp_path/'reference.wav').read_bytes()
    assert not list(tmp_path.glob('.assembly-*'))


def test_streamed_assembly_failure_preserves_prior_output(tmp_path):
    from dubbing.audio import AssemblyBuffer
    (tmp_path/'dubbed.wav').write_bytes(b'previous verified output')
    with pytest.raises(ValueError,match='silent'):
        with AssemblyBuffer(tmp_path) as buffer:
            buffer.append(np.zeros(1200,dtype=np.float32));buffer.finish()
    assert (tmp_path/'dubbed.wav').read_bytes()==b'previous verified output'
    assert not list(tmp_path.glob('.assembly-*'))


def test_pause_and_length_boundaries():
    words = [{"word": " Hello", "start": 1, "end": 2}, {"word": " there.", "start": 2.1, "end": 3}, {"word": " Again.", "start": 4, "end": 5}]
    result = segments_from_words([{"words": words}], 6, pause=0.65)
    assert [s["text"] for s in result] == ["Hello there.", "Again."]
    assert result[0]["start"] == 1 and result[1]["end"] == 5


@pytest.mark.parametrize("words", [[], [{"word": "bad", "start": float("nan"), "end": 1}], [{"word": "bad", "start": -1, "end": 1}]])
def test_no_valid_speech(words):
    with pytest.raises(ValueError, match="No timed speech"):
        segments_from_words([{"words": words}], 3)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://127.0.0.1/x", "http://[::1]/", "http://169.254.169.254", "https://user:pass@example.com", "http://example.com:8092/"])
def test_unsafe_source_rejected(url):
    with pytest.raises(ValueError):
        public_url(url)


@pytest.mark.parametrize("options", [{"language": "fr"}, {"language": "zh", "temperature": 2}, {"language": "es", "quality": "unknown"}, {"language": "es", "extra": True}])
def test_configuration_validation(options):
    with pytest.raises(ValidationError):
        Options(**options)


def test_natural_timeline_preserves_gaps_and_all_audio(tmp_path):
    (tmp_path/"segments").mkdir()
    sr = 24000
    wave = np.sin(np.arange(sr*2)*2*np.pi*220/sr).astype("float32")*0.1
    sf.write(tmp_path/"segments/00000.wav", wave, sr)
    sf.write(tmp_path/"segments/00001.wav", wave[:sr], sr)
    segments = [{"id": 0,"start": 1,"end": 2,"text": "one","translation": "uno"}, {"id": 1,"start": 3,"end": 4,"text": "two","translation": "dos"}]
    report = assemble(tmp_path, segments, Options(language="es", gap_audio="silence"), 5)
    assert report["duration"] == pytest.approx(6)
    assert [(c["output_start"], c["output_end"]) for c in report["timeline"]] == [(1, 3), (4, 5)]
    assert probe(tmp_path/"dubbed.mp3")["duration"] == pytest.approx(6, abs=.1)
    assert "00:00:04.000 --> 00:00:05.000" in (tmp_path/"translated.vtt").read_text()


def test_alignment_does_not_truncate_overlong_speech(tmp_path):
    (tmp_path/"segments").mkdir()
    wave = np.sin(np.arange(48000)*2*np.pi*220/24000)*0.1
    sf.write(tmp_path/"segments/00000.wav", wave, 24000)
    report = assemble(tmp_path, [{"id":0,"start":0,"end":1,"translation":"hola"}], Options(language="es",timing="aligned",gap_audio="silence"), 1)
    assert report["duration"] > 1.5
    assert len(report["warnings"]) == 1


def test_real_decode_and_invalid_media(tmp_path):
    source = tmp_path/"stereo.wav"
    sf.write(source, np.zeros((44100, 2)), 44100)
    dest = tmp_path/"mono.wav"
    normalize(source, dest)
    audio, sr = sf.read(dest)
    assert sr == 24000 and audio.ndim == 1
    bad = tmp_path/"bad.audio"
    bad.write_text("not an audio file")
    with pytest.raises(ValueError, match="not readable standalone audio"):
        probe(bad)


def test_uploaded_playlist_cannot_read_another_local_recording(tmp_path):
    from dubbing.audio import command

    private=tmp_path/'private.wav'
    sf.write(private,np.sin(np.arange(24000)*2*np.pi*220/24000)*.1,24000)
    mp3=tmp_path/'private.mp3'
    command(['ffmpeg','-nostdin','-v','error','-y','-i',str(private),str(mp3)])
    playlist=tmp_path/'payload.m3u8'
    playlist.write_text('#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n#EXTINF:1.0,\n'+mp3.as_uri()+'\n#EXT-X-ENDLIST\n')
    with pytest.raises(ValueError,match='standalone audio'):
        probe(playlist)
    with pytest.raises(RuntimeError,match='whitelist|Invalid data found'):
        normalize(playlist,tmp_path/'stolen.wav')


@pytest.mark.parametrize('extension',['mp3','m4a','flac','ogg'])
def test_common_audio_containers_decode_with_input_guard(tmp_path,extension):
    from dubbing.audio import command
    import os

    source=tmp_path/'tone.wav'
    sf.write(source,np.sin(np.arange(24000)*2*np.pi*220/24000)*.1,24000)
    encoded=tmp_path/('tone.'+extension)
    # A distribution decoder need not ship unrelated AAC/FLAC/Opus encoders.
    # Generate genuine fixtures with the explicitly selected reference encoder,
    # then exercise probe/normalize through the packaged tools on PATH.
    command([os.environ.get('DUBBING_TEST_ENCODER','ffmpeg'),'-nostdin','-v','error','-y','-i',str(source),str(encoded)])
    assert probe(encoded)['duration']==pytest.approx(1,abs=.15)
    normalized=tmp_path/'decoded.wav'
    normalize(encoded,normalized)
    info=sf.info(normalized)
    assert info.channels==1 and info.samplerate==24000


def test_timestamp_rounding():
    assert timestamp(59.9999) == "00:01:00.000"
    assert timestamp(3600.001) == "01:00:00.001"


def test_mandarin_spoken_pronoun_equivalence_retains_strict_score():
    from dubbing.audit import speech_scores

    assert speech_scores('它。','他','zh')==(0,1)
    assert speech_scores('她们','他们','zh')==(.5,1)
    assert speech_scores('它。','','zh')==(0,0)
    assert speech_scores('她','它','es')==(0,0)
    assert speech_scores('英国获胜','英国失败','zh')[1]<.75


def test_isolated_readback_corroborates_observed_long_file_hallucination():
    from dubbing.audit import compare_readbacks

    expected='Y lleva la vida de un general retirado que, poco a poco, comienza a desempeñar un papel más activo en la política y la vida social de la ciudad.'
    full='La ciudad de la ciudad de la ciudad '*20
    isolated='lleva la vida de un general retirado que poco a poco comienza a desempeñar un papel más activo en la política y la vida social de la ciudad.'
    result=compare_readbacks(expected,full,'es',isolated)
    assert result['full_text_similarity']<.35
    assert result['text_similarity']>.99
    assert result['full_recognized']==full and result['recognized']==isolated
    assert result['comparison_basis']=='isolated_assembled_passage'
    assert result['isolated_readback']['expected_text_prompt'] is False
    assert compare_readbacks(expected,full,'es','')['text_similarity']<.35
    assert compare_readbacks('它。','','zh','')['text_similarity']==0


def test_isolated_recheck_uses_actual_assembled_crop(tmp_path):
    from dubbing.audit import assembled_excerpt

    sr=24000
    wave=np.concatenate([np.zeros(sr),np.sin(np.arange(sr)*2*np.pi*220/sr)*.1,np.zeros(sr)])
    sf.write(tmp_path/'dubbed.wav',wave,sr)
    crop=assembled_excerpt(tmp_path,{'output_start':1,'output_end':2})
    assert len(crop)==16000 and crop.dtype==np.float32
    assert np.sqrt(np.mean(crop**2))==pytest.approx(.1/np.sqrt(2),abs=.001)
    assert np.max(np.abs(assembled_excerpt(tmp_path,{'output_start':0,'output_end':.5})))==0


def test_sentence_coverage_preserves_question_followup_and_abbreviations():
    from dubbing.translation_engines import source_sentences

    assert source_sentences("who are you, man? I'm out of here.")==["who are you, man?","I'm out of here."]
    assert source_sentences("Dr. Smith arrived in the U.S. He stayed.")==["Dr. Smith arrived in the U.S. He stayed."]
    assert source_sentences("New York would be... But the British disagreed.")==["New York would be... But the British disagreed."]


def test_translation_guard_rejects_observed_header_and_english_leakage():
    from dubbing.translation_engines import translation_problem

    assert translation_problem('it.','[Texto de Fuente]\nit.')
    assert translation_problem('it.','it.')
    assert translation_problem('it.','Eso.') is None
    assert translation_problem('Thomas Fleming.','Thomas Fleming.') is None
    assert translation_problem('IT','IT') is None
    assert translation_problem('Translation: hello.','Traducción: hola.') is None


def test_source_correction_retains_originals_and_invalidates_downstream(tmp_path):
    from dubbing.review import correct_transcript
    from dubbing.pipeline import save,read

    save(tmp_path/"transcript.json",{"text":"First. Nathan Hamm.","segments":[{"id":0,"text":"First."},{"id":1,"text":"Nathan Hamm."}]})
    save(tmp_path/"translation.json",[{"id":0,"translation":"Primero."},{"id":1,"translation":"Nathan Hamm."}])
    (tmp_path/"segments").mkdir()
    (tmp_path/"segments/00000.wav").write_bytes(b"preserved earlier passage")
    (tmp_path/"segments/00001.wav").write_bytes(b"old later passage")
    (tmp_path/"dubbed.mp3").write_bytes(b"old output")
    receipt=correct_transcript(tmp_path,{1:"Nathan Hale."},"Published source caption")
    archive=tmp_path/receipt["archive"]
    assert read(archive/"transcript.json")["segments"][1]["text"]=="Nathan Hamm."
    assert read(tmp_path/"transcript.json")["segments"][1]["text"]=="Nathan Hale."
    assert len(read(tmp_path/"translation.json"))==1
    assert (tmp_path/"segments/00000.wav").exists()
    assert not (tmp_path/"segments/00001.wav").exists()
    assert (archive/"00001.wav").exists() and (archive/"dubbed.mp3").exists()
    with pytest.raises(ValueError,match="No source text changed"):
        correct_transcript(tmp_path,{1:"Nathan Hale."},"No actual change")


def test_complete_thoughts_cover_source_and_bound_references():
    from dubbing.planning import complete_thoughts
    from dubbing.settings import options_for_job

    source=[{'id':0,'start':0,'end':12,'text':'The army crossed'}, {'id':1,'start':13,'end':25,'text':'the river.'}, {'id':2,'start':26,'end':30,'text':'Why?'}]
    result=complete_thoughts(source)
    assert [s['source_ids'] for s in result]==[[0,1],[2]]
    assert result[0]['text']=='The army crossed the river.'
    assert result[0]['reference_end']-result[0]['reference_start']<=15
    assert result[0]['source_internal_gaps'][0]['seconds']==1
    assert [s['id'] for s in result]==[0,1]
    assert Options(language='zh').semantic_translation
    assert not options_for_job({'options':{'language':'zh'}}).semantic_translation
    assert options_for_job({'options':{'language':'zh','semantic_translation':True}}).semantic_translation
    unfinished=[{**s,'text':'unfinished'} for s in source]
    assert all(s.get('planning_warning') for s in complete_thoughts(unfinished,25))


def test_source_correction_invalidates_merged_speech_id(tmp_path):
    from dubbing.review import correct_transcript
    from dubbing.pipeline import save,read

    save(tmp_path/'transcript.json',{'segments':[{'id':i,'text':str(i)} for i in range(6)]})
    save(tmp_path/'translation.json',[{'id':i,'source_ids':[2*i,2*i+1]} for i in range(3)])
    (tmp_path/'segments').mkdir()
    for i in range(3):(tmp_path/'segments'/f'{i:05}.wav').write_bytes(b'prior speech')
    receipt=correct_transcript(tmp_path,{3:'corrected'},'Recognition correction')
    assert receipt['regenerate_from_passage']==1
    assert len(read(tmp_path/'translation.json'))==1
    assert (tmp_path/'segments/00000.wav').exists()
    assert not (tmp_path/'segments/00001.wav').exists()


def test_selected_speech_retry_preserves_translation_and_prior_audio(tmp_path):
    from dubbing.review import retry_speech
    from dubbing.pipeline import save,read

    (tmp_path/"segments").mkdir()
    (tmp_path/"segments/00000.wav").write_bytes(b"keep")
    (tmp_path/"segments/00001.wav").write_bytes(b"replace")
    save(tmp_path/"translation.json",[{"id":0,"translation":"uno"},{"id":1,"translation":"dos"}])
    save(tmp_path/"audit.json",{"passed":1,"checks":2})
    receipt=retry_speech(tmp_path,[1,1],"Ambiguous pronunciation")
    assert (tmp_path/"segments/00000.wav").exists()
    assert not (tmp_path/"segments/00001.wav").exists()
    assert (tmp_path/receipt["archive"]/"00001.wav").read_bytes()==b"replace"
    assert len(read(tmp_path/"translation.json"))==2
    assert read(tmp_path/"synthesis-repairs.json")[0]["segments"]==[1]


def test_translation_postedit_keeps_other_speech_and_source_units(tmp_path):
    from dubbing.review import correct_translation
    from dubbing.pipeline import save,read

    passages=[{"id":0,"text":"A foggy day.","translation":"Un día nublado."},{"id":1,"text":"Another day.","translation":"Otro día."}]
    save(tmp_path/'translation.json',passages)
    (tmp_path/'segments').mkdir()
    (tmp_path/'segments/00000.wav').write_bytes(b'old weather speech')
    (tmp_path/'segments/00001.wav').write_bytes(b'unchanged speech')
    receipt=correct_translation(tmp_path,{0:'Un día con niebla.'},'Fog is different from clouds')
    result=read(tmp_path/'translation.json')
    assert result[0]['translation_units']==[{"source":"A foggy day.","translation":"Un día con niebla.","postedited":True}]
    assert result[1]==passages[1]
    assert (tmp_path/'segments/00001.wav').read_bytes()==b'unchanged speech'
    assert not (tmp_path/'segments/00000.wav').exists()
    assert (tmp_path/receipt['archive']/'00000.wav').read_bytes()==b'old weather speech'


def test_translation_upgrade_archives_stale_audio_and_rejects_changed_source(tmp_path):
    from dubbing.pipeline import prepare_translation,save,read

    passage={"id":0,"start":0,"end":2,"text":"A question? Another statement."}
    save(tmp_path/"transcript.json",{"segments":[passage]})
    save(tmp_path/"translation.json",[{**passage,"translation":"Only the question"}])
    (tmp_path/"segments").mkdir()
    (tmp_path/"segments/00000.wav").write_bytes(b"prior audio")
    (tmp_path/"dubbed.mp3").write_bytes(b"prior assembly")
    prepare_translation(tmp_path,Options(language="es"))
    archive=list(tmp_path.glob('translation-upgrade-*'))[0]
    assert (archive/"segments/00000.wav").read_bytes()==b"prior audio"
    assert (archive/"dubbed.mp3").read_bytes()==b"prior assembly"
    assert not (tmp_path/"translation.json").exists()
    assert read(tmp_path/"transcript.json")["segments"][0]==passage
    save(tmp_path/"translation.json",[{**passage,"translation":"Pregunta. Otra afirmación."}])
    prepare_translation(tmp_path,Options(language="es"))
    assert len(list(tmp_path.glob('translation-upgrade-*')))==1
    passage["text"]="Manually changed source"
    save(tmp_path/"transcript.json",{"segments":[passage]})
    with pytest.raises(ValueError,match="outside the review workflow"):
        prepare_translation(tmp_path,Options(language="es"))


def test_source_review_cache_merges_edits_and_preserves_conflicts(tmp_path):
    import hashlib
    from dubbing.pipeline import save,read,transcript_cache_key
    from dubbing.review import publish_source_review
    from dubbing.settings import home

    source_hash=hashlib.sha256(str(tmp_path).encode()).hexdigest()
    options=Options(language="es")
    save(tmp_path/"source.json",{"sha256":source_hash})
    archive=tmp_path/"review"
    archive.mkdir()
    save(archive/"corrections.json",{"reason":"Published caption","changes":[{"id":0,"before":"Hamm","after":"Hale"}]})
    cache=home()/"transcript-cache"/(transcript_cache_key(source_hash,options)+".json")
    cache.parent.mkdir(exist_ok=True)
    save(cache,{"segments":[{"id":0,"text":"Hamm"},{"id":1,"text":"Another reviewed correction"}]})
    assert publish_source_review(tmp_path,{"archive":"review"},options)["cache_published"]
    result=read(cache)
    assert result["segments"][0]["text"]=="Hale"
    assert result["segments"][1]["text"]=="Another reviewed correction"
    result["segments"][0]["text"]="Different correction"
    save(cache,result)
    assert not publish_source_review(tmp_path,{"archive":"review"},options)["cache_published"]
    assert read(cache)["segments"][0]["text"]=="Different correction"


def test_http_security_and_input_errors():
    from dubbing.server import app
    client = TestClient(app)
    config = client.get("/api/config").json()
    token = {"x-dubbing-token": config["token"]}
    assert client.post("/api/jobs").status_code == 403
    assert client.get("/api/config", headers={"host":"evil.example"}).status_code == 403
    assert client.post("/api/jobs", headers=token, data={"options":json.dumps({"language":"es"})}).status_code == 422
    assert client.post("/api/jobs", headers=token, data={"source":"http://127.0.0.1/private", "options":json.dumps({"language":"zh"})}).status_code == 422
    assert client.get("/api/jobs/not-a-uuid").status_code == 404
    assert client.get("/api/jobs/123/files/worker.log").status_code == 404


def test_empty_upload_removes_only_unpublished_staging_directory():
    from dubbing.server import app
    from dubbing.settings import home

    client = TestClient(app)
    token = {"x-dubbing-token":client.get("/api/config").json()["token"]}
    jobs = home()/"jobs"
    jobs.mkdir(exist_ok=True)
    before = set(jobs.iterdir())
    response = client.post("/api/jobs",headers=token,data={"options":json.dumps({"language":"es"})},files={"file":("empty.wav",b"","audio/wav")})
    assert response.status_code == 422
    assert "empty" in response.json()["detail"]
    assert set(jobs.iterdir()) == before


def test_uploaded_file_cancel_resume_and_conflicts(tmp_path):
    from dubbing.server import app
    client = TestClient(app)
    token = {"x-dubbing-token":client.get("/api/config").json()["token"]}
    audio = tmp_path/"voice.wav"
    sf.write(audio, np.zeros(24000), 24000)
    response = client.post("/api/jobs", headers=token, data={"options":json.dumps({"language":"es", "gap_audio":"silence"})}, files={"file":("voice.wav",audio.read_bytes(),"audio/wav")})
    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "queued" and job["filename"] == "voice.wav"
    endpoint = f"/api/jobs/{job['id']}"
    assert client.post(endpoint+"/speech",headers=token,json={"segments":[0],"reason":"Review test"}).status_code==409
    assert client.post(endpoint+"/transcript",headers=token,json={"edits":{"0":"Corrected"},"reason":"Review test"}).status_code==409
    assert client.post(endpoint+"/translation",headers=token,json={"edits":{"0":"Corregido"},"reason":"Review test"}).status_code==409
    assert client.post(endpoint+"/resume", headers=token).status_code == 409
    assert client.post(endpoint+"/cancel", headers=token).status_code == 200
    assert client.get(endpoint).json()["status"] == "cancelled"
    assert client.post(endpoint+"/cancel", headers=token).status_code == 409
    assert client.post(endpoint+"/resume", headers=token).json()["status"] == "queued"
    assert client.post(endpoint+"/cancel", headers=token).status_code == 200


def test_original_gap_audio_retained(tmp_path):
    sr = 24000
    original = np.ones(3*sr,dtype="float32")*.02
    sf.write(tmp_path/"source.wav",original,sr,subtype="FLOAT")
    (tmp_path/"segments").mkdir()
    sf.write(tmp_path/"segments/00000.wav",np.ones(sr,dtype="float32")*.1,sr,subtype="FLOAT")
    assemble(tmp_path,[{"id":0,"start":1,"end":2,"translation":"hola"}],Options(language="es",gap_audio="original"),3)
    dubbed,_ = sf.read(tmp_path/"dubbed.wav")
    assert dubbed[:sr].mean() == pytest.approx(.02,abs=.0001)
    assert dubbed[-sr:].mean() == pytest.approx(.02,abs=.0001)


def test_silent_source_rejected_before_recognition(tmp_path):
    silent = tmp_path/"silent.wav"
    sf.write(silent,np.zeros(24000),24000)
    with pytest.raises(ValueError,match="silent or too quiet"):
        source_signal(silent)
    voice = tmp_path/"audible.wav"
    sf.write(voice,np.sin(np.arange(24000)*2*np.pi*220/24000)*.1,24000)
    signal = source_signal(voice)
    assert .06 < signal["rms"] < .08


def test_chinese_readback_ignores_script_and_punctuation_differences():
    from dubbing.audit import canonical
    assert canonical("下一場大仗，必然會在紐約舉行。") == canonical("下一场大仗 必然会在纽约举行")
    assert canonical("纽约会") != canonical("有约会")


def test_full_readback_alignment_exposes_missing_passage():
    from dubbing.audit import align_readback
    timeline = [{"output_start":0,"output_end":2},{"output_start":3,"output_end":5},{"output_start":6,"output_end":8}]
    words = [{"start":.1,"end":1,"word":" First"},{"start":2.4,"end":2.6,"word":" gap"},{"start":6.1,"end":7,"word":" Last"}]
    recognized,gaps = align_readback(words,timeline)
    assert recognized == [" First",""," Last"]
    assert len(gaps)==1


def test_ambient_filter_handles_silence_and_short_tail():
    from dubbing.audio import ambient_without_speech
    original = np.zeros(24019,dtype=np.float32)
    filtered,masked = ambient_without_speech(original)
    assert len(filtered)==len(original)
    assert not filtered.any() and masked==0


def test_audio_connection_uses_checked_ip_and_original_tls_hostname():
    import requests
    from dubbing.sources import PublicAddressAdapter
    adapter = PublicAddressAdapter("8.8.8.8","example.com")
    prepared = requests.Request("GET","https://example.com/audio.mp3").prepare()
    pool = adapter.get_connection_with_tls_context(prepared,verify=True)
    assert pool.host=="8.8.8.8"
    assert pool.conn_kw["server_hostname"]=="example.com"
    assert pool.assert_hostname=="example.com"
    adapter.close()
