"""Keep unfinished source clauses together without changing recognition evidence."""
import re


def complete_thoughts(segments,max_seconds=60):
    result,current=[],[]

    def emit(warning=None):
        nonlocal current
        if not current:return
        candidates=[s for s in current if s['end']-s['start']<=15] or current
        reference=max(candidates,key=lambda s:s['end']-s['start'])
        row={"id":len(result),"start":current[0]['start'],"end":max(s['end'] for s in current),"text":" ".join(s['text'] for s in current),"source_ids":[s['id'] for s in current],"reference_start":reference['start'],"reference_end":reference['end'],"reference_text":reference['text'],"source_internal_gaps":[{"start":a['end'],"end":b['start'],"seconds":b['start']-a['end']} for a,b in zip(current,current[1:]) if b['start']>a['end']]}
        if warning:row['planning_warning']=warning
        result.append(row);current=[]

    for segment in segments:
        if current and segment['end']-current[0]['start']>max_seconds:
            emit('Thought exceeded the grouping limit; review cross-boundary wording')
        current.append(segment)
        text=segment['text'].rstrip()
        if re.search(r'[.!?。！？]["\'”’)]*$',text) and not text.endswith(('...','…')):
            emit()
    emit('Source ends with an unfinished thought; review translation')
    return result
