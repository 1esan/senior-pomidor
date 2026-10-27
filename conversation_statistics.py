"""Read-only conversation metrics. Never reads browser sessions or calls APIs."""
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

PEER='8491767152'

def read(path, default=None):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return {} if default is None else default

def event_time(line):
    try:return datetime.strptime(line[:23],'%Y-%m-%d %H:%M:%S,%f').timestamp()
    except ValueError:return None

def collect(base, now=None):
    base=Path(base);now=time.time() if now is None else now
    state_dir=base/'.state'
    rows={};actions={};legacy=set();warnings=[]
    def row(vid, value=None):
        vid=str(vid);value=value or {}
        return rows.setdefault(vid,{'vacancy_id':vid,'name':value.get('name') or 'Вакансия '+vid,'company':value.get('company') or 'СБЕР','status':'queued','confirmed_answers':0,'uncertain_actions':0,'last_at':None,'completed_at':None,'last_question':'','last_answer':''})
    catalog=read(state_dir/'giga-catalog.json')
    for item in catalog.get('items',[]):
        if item.get('id'):row(item['id'],item)
    boundaries=[];currents=[];started=set()
    for transport in ('web','telethon'):
        path=state_dir/'telegram-progress'/f'{transport}-live.json'
        state=read(path)
        if path.exists() and not state:warnings.append('Не удалось прочитать память '+transport)
        for key,value in state.get('completed_interviews',{}).items():
            vid=value.get('vacancy_id')
            if value.get('legacy_identity_unverified') or not value.get('intro_fingerprint'):
                legacy.add(key)
                if vid and row(vid,value)['status']!='completed':row(vid,value)['status']='legacy_review'
                continue
            if not vid:continue
            r=row(vid,value);r.update(status='completed',completed_at=value.get('completed_at'),last_at=value.get('completed_at'))
            match=re.match(PEER+r':(\d+):',value['intro_fingerprint'])
            if match:boundaries.append((int(match[1]),str(vid)))
        current=state.get('current') or {};vid=current.get('vacancy_id')
        if vid and current.get('intro_fingerprint'):
            started.add(str(vid))
            r=row(vid,current)
            match=re.match(PEER+r':(\d+):',current['intro_fingerprint'])
            if match:boundaries.append((int(match[1]),str(vid)))
            context=state.get('active_context') or {}
            if context.get('key')=='hh:'+str(vid):
                for msg in context.get('messages',[]):
                    if msg.get('role')=='assistant':r['last_answer']=msg.get('content','')[:600]
                    elif msg.get('role')=='user':r['last_question']=msg.get('content','')[:600]
            if r['status']!='completed':r['status']='paused'
            currents.append(str(vid))
        for key,status in state.get('actions',{}).items():
            if ':text:' not in key or not key.startswith(PEER+':') or status=='not_dispatched':continue
            if status=='confirmed' or actions.get(key)!='confirmed':actions[key]=status
    boundaries=sorted(set(boundaries))
    ambiguous={mid for mid,_ in boundaries if len({vid for start,vid in boundaries if start==mid})>1}
    if ambiguous:warnings.append('Есть неоднозначные привязки сообщений; ответы по этим диапазонам не распределены')
    def owner(mid):
        found=[(start,vid) for start,vid in boundaries if start<=mid]
        return found[-1][1] if found and found[-1][0] not in ambiguous else None
    for key,status in actions.items():
        match=re.match(PEER+r':(\d+):',key)
        vid=owner(int(match[1])) if match else None
        if vid:
            if status=='confirmed':rows[vid]['confirmed_answers']+=1
            else:rows[vid]['uncertain_actions']+=1
    # Timing is observed question-to-confirmation, not an assumed configured pause.
    questions={};pending=None;confirmed_events=[];delays=[];errors=[];seen=set()
    log_path=base/'logs/giga-bot.log'
    if log_path.exists():
        for line in log_path.read_text(errors='replace').splitlines():
            at=event_time(line)
            if at is None:continue
            match=re.search(r'BOT peer_id='+PEER+r' \[(\d+)\]:',line)
            if match:questions.setdefault(int(match[1]),at)
            match=re.search(r'TELEGRAM_ATTEMPT: peer_id='+PEER+r' question='+PEER+r':(\d+):',line)
            if match:pending=(int(match[1]),at)
            if 'TELEGRAM_CONFIRMED: peer_id='+PEER in line and pending:
                mid,sent_at=pending;pending=None
                if mid in seen:continue
                seen.add(mid);vid=owner(mid)
                confirmed_events.append({'at':at,'vacancy_id':vid})
                if vid:rows[vid]['last_at']=max(rows[vid]['last_at'] or 0,at)
                if mid in questions and 0<=at-questions[mid]<=3600:delays.append(at-questions[mid])
            if re.search(r'\bERROR\b|MODEL_FAILURE:|Действие остановлено',line):
                errors.append({'at':at,'message': 'Временный сбой генерации Luna' if 'MODEL_FAILURE:' in line else 'Ошибка выполнения; подробности в журнале запуска'})
    runtime=read(state_dir/'giga-autonomous.json')
    job=read(state_dir/'jobs'/(str(runtime.get('job_id',''))+'.json'))
    live=job.get('mode')=='live' and job.get('status') in ('running','stopping')
    try:os.kill(int(runtime.get('pid',0)),0) if isinstance(runtime.get('pid'),int) and runtime['pid']>0 else (_ for _ in ()).throw(ProcessLookupError())
    except (OSError,ValueError,TypeError):live=False
    phase=runtime.get('phase');vid=str(runtime.get('vacancy_id',''))
    if vid in rows and rows[vid]['status']!='completed' and job.get('mode')=='live':
        r=rows[vid]
        if live:
            r['status']={'waiting_recruiter':'waiting_recruiter','reply_delay':'reply_delay','generating':'generating','model_retry':'model_retry'}.get(phase,'running')
        elif job.get('status') in ('failed','needs_attention'):r['status']='error'
        r['runtime_message']=runtime.get('message','')[:400]
        r['last_at']=max(r['last_at'] or 0,runtime.get('updated_at') or 0)
        if live:r['send_after']=runtime.get('send_after') if phase=='reply_delay' else None
    verified=sum(r['status']=='completed' for r in rows.values())
    today=datetime.fromtimestamp(now).date()
    today_events=[e for e in confirmed_events if datetime.fromtimestamp(e['at']).date()==today]
    confirmed=sum(v=='confirmed' for v in actions.values())
    # HH uses the last full local export; timestamps explicitly disclose freshness.
    hh=read(base/'hh-data.json');hh_rows=[]
    for r in hh.get('rows',[]):
        if not r.get('msgs_employer'):continue
        hh_rows.append({'id':r['id'],'company':r.get('employer'),'name':r.get('position'),'status':r.get('state_name') or r.get('state'),'waiting_us':bool(r.get('unanswered') and r.get('state')=='response'),'messages_in':r.get('msgs_employer',0),'messages_out':r.get('msgs_applicant',0),'last_at':r.get('updated_at'),'last_text':r.get('last_text','')[:400]})
    from application_status import enrich
    application_status=enrich(rows,base,started)
    return {'generated_at':now,'applications':application_status,'telegram':{'rows':sorted(rows.values(),key=lambda r:(r['status']=='queued',-(r['last_at'] or 0),r['vacancy_id'])),'confirmed_answers':confirmed,'confirmed_today':len(today_events),'completed':verified,'legacy_completed':len(legacy),'uncertain_actions':sum(v!='confirmed' for v in actions.values()),'mean_response_seconds':round(sum(delays)/len(delays),1) if delays else None,'timing_samples':len(delays),'errors_today':sum(datetime.fromtimestamp(e['at']).date()==today for e in errors),'errors':errors[-12:][::-1],'live':live,'warnings':warnings},'hh':{'generated_at':hh.get('generated_at'),'rows':hh_rows,'waiting_us':sum(r['waiting_us'] for r in hh_rows)}}
