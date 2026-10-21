import pytest

from dubbing.numbers import spanish_speech, numeric_readback
from dubbing.audit import compare_readbacks, passage_passed


@pytest.mark.parametrize('source,expected',[
    ('3,000 soldados y 130 barcos','tres mil soldados y ciento treinta barcos'),
    ('el 21 de septiembre de 1776','el veintiuno de septiembre de mil setecientos setenta y seis'),
    ('30.000 hombres','treinta mil hombres'),
    ('1,234.50 y 1.234,50','mil doscientos treinta y cuatro coma cinco cero y mil doscientos treinta y cuatro coma cinco cero'),
    ('-3,05 grados','menos tres coma cero cinco grados'),
    ('0.125','cero coma uno dos cinco'),
    ('1–2','uno a dos'),
    ('12:30 y 1/2 y 21º','12:30 y 1/2 y 21º'),
])
def test_spanish_speech_numbers(source,expected):
    assert spanish_speech(source)==expected


@pytest.mark.parametrize('expected,recognized,passed',[
    ('3,000 soldados','tres soldados',False),
    ('30,000 hombres y 130 barcos','treinta mil hombres y treinta barcos',False),
    ('30,000 hombres y 130 barcos','treinta mil hombres y ciento treinta barcos',True),
    ('en 1776','en mil seiscientos seis',False),
    ('9,000 personas','nueve mil personas',True),
    ('20,000 y 20,000','veinte mil',False),
    ('130 y 3000','tres mil y ciento treinta',False),
    ('un hombre','el hombre',True),
    ('1 hombre','el hombre',False),
    ('veinte mil hombres','veinte hombres',False),
    ('12:30','doce treinta',False),
    ('-3 grados','tres grados',False),
    ('-3,05 grados','menos tres coma cero cinco grados',True),
])
def test_numeric_consistency(expected,recognized,passed):
    assert (numeric_readback(expected,recognized,'es')['status']=='passed')==passed


def test_high_text_similarity_cannot_hide_wrong_number():
    expected='El general reunió 3,000 soldados para defender la ciudad en aquella batalla.'
    result=compare_readbacks(expected,expected.replace('3,000','3'),'es')
    assert result['text_similarity']>.9
    assert not passage_passed({**result,'clipped_fraction':0,'rms':.1})


def test_crop_with_correct_numbers_wins_over_higher_wrong_character_score():
    result=compare_readbacks('Había 3,000 soldados en esa ciudad.','Había 3 soldados en esa ciudad.','es','Tres mil soldados estaban allí.')
    assert result['numeric_check']['status']=='passed'
    assert result['comparison_basis']=='isolated_assembled_passage'
    assert result['full_numeric_check']['status']=='review_required'


def test_mandarin_numbers_are_explicitly_not_certified():
    assert numeric_readback('三千人','三个人','zh')['status']=='not_evaluated'


@pytest.mark.parametrize('language,text',[('zh','它。'),('es','Es eso.')])
def test_unchanged_speech_retains_existing_qwen_cache_fingerprint(language,text):
    import hashlib,json
    from dubbing.pipeline import qwen_inputs
    from dubbing.settings import Options
    segment={'id':0,'start':0.,'end':1.,'translation':text}
    options=Options(language=language)
    previous={'segment':segment,'reference_sha256':'source','voice_revision':'voice','language':language,'seed':42,'temperature':.6,'repair_count':0,'conditioning_version':2}
    expected=hashlib.sha256(json.dumps(previous,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    fingerprint,spoken=qwen_inputs(segment,'source',options,0,'voice')
    assert fingerprint==expected and spoken==text


def test_qwen_speech_numbers_do_not_change_captions_and_invalidate_only_changed_input():
    from dubbing.pipeline import qwen_inputs
    from dubbing.settings import Options
    segment={'id':0,'start':0.,'end':8.,'translation':'En 1777 había 17,000 hombres.'}
    fingerprint,spoken=qwen_inputs(segment,'source',Options(language='es'),0,'voice')
    assert spoken=='En mil setecientos setenta y siete había diecisiete mil hombres.'
    assert segment['translation']=='En 1777 había 17,000 hombres.'
    changed,_=qwen_inputs({**segment,'translation':'En 1776 había 17,000 hombres.'},'source',Options(language='es'),0,'voice')
    assert changed!=fingerprint
