"""Configuration and real-source reference bounds for the isolated renderer."""
import pytest
from pydantic import ValidationError

from dubbing.indextts import reference_window, spoken_text, short_utterance_fallback
from dubbing.settings import Options, options_for_job


def test_short_thought_uses_whole_performance():
    assert reference_window({'start':10.,'end':14.,'reference_start':12.,'reference_end':14.})==(10.,14.)


def test_long_thought_uses_existing_reference_boundary():
    assert reference_window({'start':10.,'end':45.,'reference_start':22.,'reference_end':34.})==(22.,34.)


def test_tiny_interjection_uses_nearby_source_and_stays_in_file():
    assert reference_window({'start':.1,'end':.2},3.)==(0,3.)
    assert reference_window({'start':9.8,'end':9.9},10.)==pytest.approx((7.8,10.))


def test_old_jobs_keep_their_qwen_engine():
    options=options_for_job({'options':{'language':'zh'}})
    assert options.tts_engine=='qwen' and not options.semantic_translation


def test_editorial_dashes_become_pauses_before_number_normalization():
    assert spoken_text('第二天——也就是1776年8月——英军','zh')=='第二天，也就是1776年8月，英军'
    assert spoken_text('La ciudad — aunque pequeña — resistió.','es')=='La ciudad ,  aunque pequeña ,  resistió.'


def test_quotation_marks_are_not_spoken_but_words_are_retained():
    assert spoken_text('他们问：“喂，你是谁？”','zh')=='他们问：喂，你是谁？'


def test_numeric_ranges_and_negative_signs_are_preserved():
    assert spoken_text('温度-3度，范围1–2。','zh')=='温度-3度，范围1–2。'


@pytest.mark.parametrize('text,duration,language,expected',[('它。',.16,'zh',True),('她？',.7,'zh',True),('他说它。',.16,'zh',False),('It.',.16,'es',False),('它。',4.,'zh',False)])
def test_short_fallback_is_limited_to_verified_mandarin_pronoun_case(text,duration,language,expected):
    assert short_utterance_fallback({'translation':text,'start':0.,'end':duration},language)==expected


@pytest.mark.parametrize('values',[{'tts_engine':'indextts2'},{'emotion_strength':1.1},{'emotion_strength':-.1},{'reference_mode':'detected_speakers'},{'indextts_text_tokens':41},{'indextts_text_tokens':19}])
def test_unsupported_engine_or_delivery_controls_rejected(values):
    with pytest.raises(ValidationError):Options(language='es',**values)
