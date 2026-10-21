"""Deterministic Spanish speech numbers and an independent ASR number screen."""
from collections import Counter
from decimal import Decimal
import re

TOKEN = re.compile(r'(?<![\w])[-+]?\d+(?:[.,]\d+)*(?:[ºª°])?(?![\w])')


def value(token):
    """Accept integers, conventional grouped thousands, and decimal fractions.

    A nonzero leading group followed by exactly three digits is thousands
    (3,000 / 3.000). Ambiguous three-place decimals need editorial spelling.
    Reject mixed/malformed grouping rather than guessing a different value.
    """
    sign = '-' if token.startswith('-') else ''
    raw = token.lstrip('+-')
    if re.fullmatch(r'\d+', raw):
        return Decimal(sign + raw)
    if re.fullmatch(r'[1-9]\d{0,2}([.,])\d{3}(?:\1\d{3})*', raw):
        return Decimal(sign + raw.replace(',', '').replace('.', ''))
    if raw.count(',') + raw.count('.') == 1:
        return Decimal(sign + raw.replace(',', '.'))
    # Both locale conventions: 1,234.50 and 1.234,50.
    if ',' in raw and '.' in raw:
        decimal = ',' if raw.rfind(',') > raw.rfind('.') else '.'
        grouping = '.' if decimal == ',' else ','
        integer, fraction = raw.rsplit(decimal, 1)
        if re.fullmatch(r'[1-9]\d{0,2}(?:' + re.escape(grouping) + r'\d{3})+', integer) and fraction.isdigit():
            return Decimal(sign + integer.replace(grouping, '') + '.' + fraction)
    raise ValueError('Unsupported numeric notation: ' + token)


def literals(text):
    found, unsupported = [], []
    for match in TOKEN.finditer(text):
        token = match.group()
        # Fractions, clock times, identifiers and ordinal suffixes require a
        # separate reading. Do not silently turn their pieces into cardinals.
        before, after = text[max(0, match.start()-1):match.start()], text[match.end():match.end()+1]
        try:
            if before in {'/', ':'} or after in {'/', ':'}:
                raise ValueError('compound notation')
            number = value(token)
        except ValueError:
            unsupported.append(token)
        else:
            found.append((match, number))
    return found, unsupported


def spanish_speech(text):
    from num2words import num2words

    text = re.sub(r'(?<=\d)[–—](?=\d)', ' a ', text)
    found, _ = literals(text)
    for match, number in reversed(found):
        magnitude = abs(number)
        integral, _, fraction = format(magnitude, 'f').partition('.')
        spoken = num2words(int(integral), lang='es')
        if fraction:
            # Preserve decimal precision, including leading/trailing zeroes.
            spoken += ' coma ' + ' '.join(num2words(int(d), lang='es') for d in fraction)
        if number < 0:
            spoken = 'menos ' + spoken
        text = text[:match.start()] + spoken + text[match.end():]
    return text


def numeric_readback(expected, recognized, language):
    if language != 'es':
        return {'status': 'not_evaluated', 'reason': 'Spanish number screen only'}
    from text_to_num import alpha2digit

    expected_literals, unsupported = literals(expected)
    # Expand digits before parsing words so grouped commas are never mistaken
    # for decimal separators by the ASR number parser.
    def parsed(text):
        converted=alpha2digit(spanish_speech(text), 'es', threshold=0)
        # text2num deliberately leaves signs as words; retain their meaning.
        converted=re.sub(r'\bmenos\s+(?=\d)', '-', converted, flags=re.IGNORECASE)
        return literals(converted)[0]
    expected_values = parsed(expected)
    actual_values = parsed(recognized)
    explicit = Counter(n for _, n in expected_literals)
    # Articles un/una are parsed as one; require ones only when explicit digits
    # requested them. Retain every other number, including written-out counts.
    required = [n for _, n in expected_values if n != 1 or explicit[Decimal(1)]]
    observed = [n for _, n in actual_values]
    remaining = iter(observed)
    ordered = all(any(candidate == n for candidate in remaining) for n in required)
    missing = list((Counter(required) - Counter(observed)).elements())
    return {'status': 'passed' if ordered and not unsupported else 'review_required',
            'expected': [str(n) for n in required], 'recognized': [str(n) for n in observed],
            'missing': [str(n) for n in missing], 'order_matches': ordered,
            'unsupported_notation': unsupported,
            'limitation': 'Unprompted ASR number consistency screen; ambiguous grouping and ASR errors require listening review.'}
