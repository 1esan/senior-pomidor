"""Own HH negotiation status snapshots, keyed by vacancy AND application ID."""
import json,re
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit

def timestamp(value):
    try:
        if isinstance(value,(int,float)):return float(value)
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        return dt.replace(tzinfo=timezone.utc).timestamp() if dt.tzinfo is None else dt.timestamp()
    except (ValueError,TypeError,AttributeError):return None

def vacancy_id(url):
    try:
        u=urlsplit(url or '')
        if u.scheme not in ('http','https') or not re.fullmatch(r'(?:[a-z0-9-]+\.)?hh\.ru',u.hostname or ''):return None
        m=re.fullmatch(r'/vacancy/(\d+)/?',u.path);return m[1] if m else None
    except ValueError:return None

def normalise(raw):
    v=raw.get('vacancy') or {};employer=v.get('employer') or {}
    url=v.get('alternate_url') or raw.get('url') or raw.get('vacancy_url')
    vid=str(v.get('id') or raw.get('vacancy_id') or vacancy_id(url) or '')
    if not vid.isdigit() or not raw.get('id'):return None
    linked=vacancy_id(url)
    if linked and linked!=vid:raise ValueError('Conflicting vacancy identity')
    state=raw.get('state');state=state.get('id') if isinstance(state,dict) else state
    return {'id':str(raw['id']),'vacancy_id':vid,'state':state,'employer_id':str(employer.get('id') or raw.get('employer_id') or ''),'company':employer.get('name') or raw.get('company') or raw.get('employer') or '', 'name':v.get('name') or raw.get('name') or raw.get('position') or 'Вакансия '+vid,'created_at':raw.get('created_at') or raw.get('created'),'updated_at':raw.get('updated_at') or raw.get('updated')}

def load(path):
    try:return json.loads(Path(path).read_text())
    except (ValueError,OSError):return {}

def publish_snapshot(base,raw_rows,generated_at,observed_since=None):
    from runtime import save_json
    target=Path(base)/'.state/hh-negotiation-statuses.json';previous=load(target)
    at=timestamp(generated_at)
    if at is None:raise ValueError('Missing snapshot date')
    if (timestamp(previous.get('generated_at')) or 0)>at:return previous
    normalised=[r for item in raw_rows if (r:=normalise(item))]
    rows=list({r['id']:r for r in normalised}.values());history=previous.get('history',{}).copy()
    for row in rows:
        item=dict(history.get(row['id'],{}))
        if item.get('vacancy_id') not in (None,row['vacancy_id']):item={}
        if row['state']=='discard':
            if item.get('last_state')!='discard':item['rejection_first_seen_at']=at
        else:
            item['rejection_first_seen_at']=None
            if row['state'] in ('response','invitation','interview') and timestamp(observed_since) is not None:item['last_non_rejected_at']=timestamp(observed_since)
        item.update(vacancy_id=row['vacancy_id'],last_state=row['state'],last_seen_at=at);history[row['id']]=item
    snapshot={'schema_version':1,'complete':True,'generated_at':generated_at,'rows':rows,'history':history}
    save_json(target,snapshot);return snapshot

def status_source(base):
    base=Path(base);snapshot=load(base/'.state/hh-negotiation-statuses.json');full=load(base/'hh-data.json')
    candidates=[]
    if snapshot.get('complete') and timestamp(snapshot.get('generated_at')) is not None:candidates.append(snapshot)
    if full.get('complete') is not False and timestamp(full.get('generated_at')) is not None:
        candidates.append({'generated_at':full['generated_at'],'rows':[r for x in full.get('rows',[]) if (r:=normalise(x))],'history':snapshot.get('history',{})})
    return max(candidates,key=lambda x:timestamp(x['generated_at'])) if candidates else {'rows':[],'history':{},'generated_at':None}

def is_sber(row):
    return row.get('employer_id')=='3529' or row.get('company','').strip().casefold() in {'сбер','сбербанк','пао сбербанк','sber'}

def journey(stage,outcome,telegram_invitation=False):
    if outcome=='rejected':
        if stage=='completed':return 'rejected_completed','Отказ · интервью пройдено'
        if stage=='unknown':return 'rejected_unverified','Отказ · прохождение интервью не подтверждено'
        return 'rejected_unfinished','Отказ · интервью не пройдено'
    if outcome=='withdrawn':
        return 'withdrawn',('Отклик отозван · интервью пройдено' if stage=='completed' else 'Отклик отозван')
    if stage=='completed':return 'completed_waiting','Интервью пройдено · ожидается обратная связь'
    if stage=='in_progress':return 'interview_in_progress','Интервью в процессе'
    if stage=='unknown':return 'needs_review','Нужно проверить прохождение интервью'
    if telegram_invitation:return 'waiting_interview','Ожидает интервью в Telegram'
    return 'applied','Отклик отправлен'

def enrich(rows,base,started):
    source=status_source(base);grouped={};telegram_invited=set(rows)
    for item in source['rows']:
        grouped.setdefault(item['vacancy_id'],[]).append(item)
        if is_sber(item) and item['vacancy_id'] not in rows:
            vid=item['vacancy_id'];rows[vid]={'vacancy_id':vid,'name':item['name'],'company':item['company'],'status':'queued','confirmed_answers':0,'uncertain_actions':0,'last_at':None,'completed_at':None,'last_question':'','last_answer':''}
    counts=dict(rejected=0,completed_and_rejected=0,rejected_without_completion=0,rejected_after_interview_confirmed=0,awaiting_outcome=0,status_unknown=0)
    for vid,row in rows.items():
        stage='completed' if row['status']=='completed' else 'unknown' if row['status']=='legacy_review' else 'in_progress' if vid in started or row['confirmed_answers'] else 'not_started'
        matches=grouped.get(vid,[])
        # A past rejected application must not hide a new application to the same vacancy.
        matches.sort(key=lambda x:(timestamp(x['created_at']) or 0,timestamp(x['updated_at']) or 0,x['id']),reverse=True)
        item=matches[0] if matches else None
        if len(matches)>1 and not timestamp(matches[0]['created_at']):item=None
        state=item['state'] if item else None
        outcome='rejected' if state=='discard' else 'withdrawn' if state=='discard_by_applicant' else 'invited' if state in ('invitation','interview') else 'pending' if state=='response' else 'unknown'
        row.update(interview_stage=stage,application_state=state,application_outcome=outcome,application_id=item['id'] if item else None,application_updated_at=item['updated_at'] if item else None,application_snapshot_at=source.get('generated_at'),rejection_sequence=None)
        label={'rejected':'Отказ','withdrawn':'Отклик отозван','invited':'Приглашение','pending':'Отклик отправлен','unknown':'Статус HH неизвестен'}[outcome]
        if outcome=='rejected':
            counts['rejected']+=1
            if stage=='completed':
                counts['completed_and_rejected']+=1
                h=source.get('history',{}).get(item['id'],{});done=timestamp(row.get('completed_at'));seen=h.get('rejection_first_seen_at');prior=h.get('last_non_rejected_at')
                if h.get('last_state')=='discard' and done is not None and seen is not None and prior is not None and done<=prior<seen:
                    row['rejection_sequence']='after_interview';label='Отказ после интервью';counts['rejected_after_interview_confirmed']+=1
                else:
                    row['rejection_sequence']='before_completion' if done is not None and seen is not None and seen<done else 'unknown'
            else:counts['rejected_without_completion']+=1
        elif outcome!='withdrawn' and stage=='completed':counts['awaiting_outcome']+=1
        if outcome=='unknown':counts['status_unknown']+=1
        row['application_label']=label
        row['telegram_invitation_confirmed']=vid in telegram_invited
        row['journey_code'],row['journey_label']=journey(stage,outcome,vid in telegram_invited)
    return {'generated_at':source.get('generated_at'),'counts':counts,'monitor':load(Path(base)/'.state/hh-status-monitor.json')}
