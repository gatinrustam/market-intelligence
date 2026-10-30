import hashlib
import json
import re
from datetime import datetime,timezone


def exact_key(event_type,actor,event_time,precision,namespace):
    if not all((actor,event_time,namespace)) or precision not in ('date','date_range'):
        return None
    components={'type':event_type,'actor':actor,'time':event_time,'precision':precision,'namespace':namespace}
    return hashlib.sha256(json.dumps(components,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def primary_actor(actors):
    return next((a['entity_id'] for a in actors if a['role']=='issuer' and a['resolution']=='canonical'),None)


def title_tokens(title):
    return set(re.findall(r'\w+',title.casefold(),flags=re.UNICODE)) - {'the','a','an','of','and','to','for','in','on','with','at'}


def jaccard(left,right):
    a,b=title_tokens(left),title_tokens(right)
    return len(a&b)/len(a|b) if a and b else 0.0


def parse_timestamp(value):
    return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc) if value else None


def suggestion(left,right,config):
    same_type=left['taxonomy']['event_type']==right['taxonomy']['event_type']
    actor=primary_actor(left['actors'])
    same_actor=actor is not None and actor==primary_actor(right['actors'])
    if not same_type or not same_actor or set(left['jurisdictions'])!=set(right['jurisdictions']):
        return None
    a,b=left['time'],right['time']
    if a['event_time'] and b['event_time'] and a['event_time']!=b['event_time']:
        return None
    t1,t2=map(parse_timestamp,(a['earliest_source_published_at'],b['earliest_source_published_at']))
    distance=abs((t1-t2).total_seconds()) if t1 and t2 else None
    if distance is None or distance>config.time_window_seconds:
        return None
    similarity=jaccard(left['content']['canonical_title'],right['content']['canonical_title'])
    if similarity<config.title_jaccard_threshold:
        return None
    return {'same_event_type':True,'same_primary_actor':True,'title_similarity':similarity,
            'time_distance_seconds':distance,'time_distance_basis':'source_publication',
            'suggestion_reason':'title_overlap_same_type_actor_near_publication'}
