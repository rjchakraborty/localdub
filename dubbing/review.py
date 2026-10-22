"""Source-text corrections with retained originals and downstream invalidation."""
import time
from uuid import uuid4

from .pipeline import read, save


def correct_transcript(folder, edits, reason):
    transcript = read(folder/"transcript.json")
    segments = transcript["segments"]
    by_id = {s["id"]:s for s in segments}
    if not edits or not set(edits).issubset(by_id):
        raise ValueError("Corrections must reference existing passage IDs")
    changes = [{"id":i,"before":by_id[i]["text"],"after":text.strip()} for i,text in edits.items() if by_id[i]["text"]!=text.strip()]
    if not changes:
        raise ValueError("No source text changed")
    archive = folder/("source-review-"+str(uuid4()))
    archive.mkdir()
    save(archive/"corrections.json",{"time":time.time(),"reason":reason,"changes":changes})
    first = min(c["id"] for c in changes)
    # Preserve the prior transcript before publishing its corrected replacement.
    save(archive/"transcript.json",transcript)
    for change in changes:
        by_id[change["id"]]["text"] = change["after"]
    transcript["text"] = " ".join(s["text"] for s in segments)
    transcript.setdefault("source_reviews",[]).append(str(archive.name))
    save(folder/"transcript.json",transcript)
    translation = folder/"translation.json"
    if translation.exists():
        previous = read(translation)
        affected=[s['id'] for s in previous if any(i>=first for i in s.get('source_ids',[s['id']]))]
        first=min(affected,default=len(previous))
        translation.replace(archive/translation.name)
        save(translation,[s for s in previous if s["id"]<first])
    for path in (folder/"segments").glob("*"):
        prefix = path.name.split(".")[0].split("-")[0]
        if prefix.isdigit() and int(prefix)>=first:
            path.replace(archive/path.name)
    for name in ("dubbed.wav","dubbed.mp3","translated.vtt","report.json","audit.json","readback.json","progress.json"):
        path = folder/name
        if path.exists():
            path.replace(archive/name)
    return {"archive":archive.name,"changed_passages":len(changes),"regenerate_from_passage":first}


def retry_speech(folder,indices,reason):
    archive=folder/("speech-review-"+str(uuid4()))
    archive.mkdir()
    events_path=folder/"synthesis-repairs.json"
    events=read(events_path) if events_path.exists() else []
    event={"segments":sorted(set(indices)),"reason":reason,"time":time.time(),"requested_review":True}
    save(archive/"request.json",event)
    for index in event["segments"]:
        for suffix in (".wav",".json"):
            path=folder/"segments"/f"{index:05}{suffix}"
            if path.exists():path.replace(archive/path.name)
    for name in ("dubbed.wav","dubbed.mp3","translated.vtt","report.json","audit.json","readback.json","progress.json"):
        path=folder/name
        if path.exists():path.replace(archive/name)
    events.append(event)
    save(events_path,events)
    return {"archive":archive.name,"regenerate_passages":event["segments"]}


def correct_translation(folder,edits,reason):
    passages=read(folder/"translation.json")
    by_id={s["id"]:s for s in passages}
    if not edits or not set(edits).issubset(by_id):
        raise ValueError('Corrections must reference existing translated passage IDs')
    changes=[{"id":i,"source":by_id[i]["text"],"before":by_id[i]["translation"],"after":text.strip()} for i,text in edits.items() if by_id[i]["translation"]!=text.strip()]
    if not changes:raise ValueError('No translated text changed')
    archive=folder/('translation-review-'+str(uuid4()))
    archive.mkdir()
    save(archive/'translation.json',passages)
    save(archive/'corrections.json',{"time":time.time(),"reason":reason,"changes":changes})
    for change in changes:
        passage=by_id[change['id']]
        passage['translation']=change['after']
        passage['translation_units']=[{"source":passage['text'],"translation":change['after'],"postedited":True}]
        passage.setdefault('translation_reviews',[]).append(archive.name)
        passage['meaning_check']='Post-edited; original machine translation retained in review archive'
        for suffix in ('.wav','.json','-timed.wav'):
            path=folder/'segments'/f"{change['id']:05}{suffix}"
            if path.exists():path.replace(archive/path.name)
    save(folder/'translation.json',passages)
    for name in ('dubbed.wav','dubbed.mp3','translated.vtt','report.json','audit.json','readback.json','progress.json'):
        path=folder/name
        if path.exists():path.replace(archive/name)
    return {"archive":archive.name,"changed_passages":[c['id'] for c in changes]}


def publish_source_review(folder,receipt,options):
    """Reuse reviewed source text across languages without overwriting another correction."""
    from .pipeline import transcript_cache_key
    from .settings import home

    source=read(folder/"source.json")
    cache=home()/"transcript-cache"/(transcript_cache_key(source.get("processing_sha256", source["sha256"]),options)+".json")
    if not cache.exists():return {"cache_published":False,"cache_warning":"No matching recognition cache exists"}
    canonical=read(cache)
    review=read(folder/receipt["archive"]/"corrections.json")
    by_id={s["id"]:s for s in canonical["segments"]}
    if any(c["id"] not in by_id or by_id[c["id"]]["text"] not in {c["before"],c["after"]} for c in review["changes"]):
        return {"cache_published":False,"cache_warning":"Another cached source correction differs; job correction retained without overwriting it"}
    changed=False
    for correction in review["changes"]:
        segment=by_id[correction["id"]]
        changed=changed or segment["text"]!=correction["after"]
        segment["text"]=correction["after"]
    if changed:
        canonical["text"]=" ".join(s["text"] for s in canonical["segments"])
        canonical.setdefault("review_provenance",[]).append({**review,"source_job":folder.name,"archive":receipt["archive"]})
        save(cache,canonical)
    return {"cache_published":True}
