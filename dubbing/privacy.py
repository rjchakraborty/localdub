"""Remove URL credentials from portable metadata; originals stay local."""
import re
from urllib.parse import urlsplit, urlunsplit


def public_metadata(value):
    if isinstance(value,dict):
        return {key:public_metadata(item) for key,item in value.items()}
    if isinstance(value,list):
        return [public_metadata(item) for item in value]
    if isinstance(value,str):
        def redact(match):
            parts=urlsplit(match.group())
            return urlunsplit((parts.scheme,parts.netloc.rsplit('@',1)[-1],parts.path,'',''))
        return re.sub(r'https?://[^\s<>"\u0027]+',redact,value)
    return value
