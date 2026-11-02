from python_runtime import python_command
"""Allowlisted operation launcher, finite loops and explicit stop."""
import json,os,re,signal,subprocess,sys,threading,time,uuid
from pathlib import Path
from common import BASE
from search_options import resolve_search_fields
from runtime import save_json
LOCK=threading.RLock();JOBS={}
for saved in sorted((BASE/'.state/jobs').glob('*.json'),key=lambda p:p.stat().st_mtime)[-30:]:
    try:
        previous=json.loads(saved.read_text())
        if previous.get('status') in ('running','stopping'):
            previous.update(status='failed',message='Предыдущая сессия панели прервана; проверь её журнал')
        JOBS[previous['id']]=previous
    except (ValueError,KeyError):pass

def number(o,k,default,lo,hi):
    value=o.get(k,default)
    if isinstance(value,bool):raise ValueError('Некорректное число '+k)
    n=int(value)
    if not lo<=n<=hi:raise ValueError('Вне диапазона: '+k)
    return n
def text(o,k,default='',length=1000):
    s=o.get(k,default)
    if not isinstance(s,str) or len(s)>length or '\x00' in s:raise ValueError('Некорректный текст '+k)
    return s
def command_for(action,o):
    if not isinstance(o,dict):raise ValueError('Ожидаются параметры')
    mode=o.get('mode','preview')
    if mode not in ('preview','live'):raise ValueError('Неизвестный режим')
    live=mode=='live'
    if live and o.get('confirm_live') is not True:raise ValueError('Для отправки нужно явное подтверждение в панели')
    if action in ('apply','reply'):
        cmd=['hh.py',action]
        if live:cmd+=['--live']
        rid=text(o,'resume_id',length=100)
        if rid:
            if not re.fullmatch(r'[a-zA-Z0-9_-]+',rid):raise ValueError('Неверный ID резюме')
            cmd+=['--resume-id',rid]
        if action=='apply':
            preset=o.get('preset','moscow')
            if preset not in ('moscow','ru-cis','abroad','all'):raise ValueError('Неизвестная география')
            cmd+=['--preset',preset,'--max',str(number(o,'max',10,1,1000)),'--pages',str(number(o,'pages',1,1,100)),'--per-page',str(number(o,'per_page',15,1,100))]
            queries=text(o,'queries','',5000)
            if o.get('all_queries') is True:cmd+=['--all-queries']
            else:
                q=[v.strip() for v in queries.splitlines() if v.strip()]
                if not q or len(q)>30 or any(v.startswith('-') for v in q):raise ValueError('От 1 до 30 запросов')
                cmd+=['--queries',*q]
            ids=text(o,'employer_ids',length=500)
            if ids:
                items=re.split(r'[,\s]+',ids.strip())
                if any(not i.isdigit() for i in items):raise ValueError('ID компаний — числа через запятую')
                cmd+=['--employer-id',*items]
            cmd+=['--search-fields',*resolve_search_fields(o.get('search_fields'),body_too=o.get('body_too') is True)]
            if o.get('solve_tests') is True:cmd+=['--solve-tests']
            if o.get('no_sber') is True:cmd+=['--no-sber']
        else:cmd+=['--period',str(number(o,'period',45,1,365)),'--pages',str(number(o,'pages',25,1,100)),'--loop-minutes',str(number(o,'minutes',0,0,1440)),'--every-sec',str(number(o,'interval',300,30,86400))]
        return cmd,'hh'
    if action in ('giga-web','giga-telethon'):
        cmd=['giga-bot.py' if action=='giga-web' else 'giga-recruiter.py','--minutes',str(number(o,'minutes',60,1,1440)),'--strategy',o.get('strategy','first')]
        if cmd[-1] not in ('first','senior'):raise ValueError('Неизвестная стратегия')
        if live:cmd+=['--live']
        elif o.get('inspect') is True:cmd+=['--inspect']
        else:cmd+=['--dry-run']
        if o.get('auto_next',True) is False:cmd+=['--no-auto-next']
        if action=='giga-web' and o.get('autonomous') is True:
            vid=text(o,'vacancy_id',length=20)
            if not live or vid and not vid.isdigit():raise ValueError('Для автономного режима нужна отправка; ID начальной вакансии необязателен и должен быть числом')
            cmd+=['--autonomous']
            if vid:cmd+=['--vacancy-id',vid]
        if action=='giga-telethon':
            cfg=BASE/'.state/telethon-config.json'
            if not cfg.is_file():raise ValueError('Сначала добавьте Telethon API ID/API Hash и выполните вход через Подключить_Telethon.command')
        return cmd,'telegram'
    if action=='watch':return ['bot_cli.py','watch','--minutes',str(number(o,'minutes',60,1,1440)),'--interval',str(number(o,'interval',300,300,86400))],'hh'
    if action in ('contacts','bump','audit'):
        cmd=[{'contacts':'hh-tg-blast.py','bump':'hh-bump16.py','audit':'hh-audit-location.py'}[action]]
        if live:
            if action=='audit':raise ValueError('Отзыв доступен из терминала с отдельным подтверждением')
            cmd+=['--send']
        if action=='contacts':cmd+=['--limit='+str(number(o,'max',10,1,1000)),'--cooldown='+str(number(o,'interval',30,10,86400))]
        return cmd,'hh'
    if action in ('whoami','resumes'):return ['hh.py',action],'hh'
    raise ValueError('Неизвестное действие')

def public(job):
    result={k:v for k,v in job.items() if k!='process'}
    if job.get('action') in ('giga-web','giga-telethon'):
        result['previous_version']=job.get('started_at',0)<(BASE/'giga-bot.py').stat().st_mtime
    from hh_captcha import read_state
    challenge=read_state(BASE)
    if challenge.get('job_id')==job.get('id') and job.get('status')=='running' and challenge.get('status') in ('waiting','resume_requested','checking'):
        result['message']=challenge.get('message')
        result['captcha_waiting']=True
    try:ai=json.loads((BASE/'.state/ai-wait.json').read_text())
    except (FileNotFoundError,ValueError):ai={}
    if ai.get('job_id')==job.get('id') and job.get('status')=='running' and ai.get('status')=='waiting':
        result['message']=ai.get('message');result['ai_waiting']=True
    try:a=json.loads((BASE/'.state/giga-autonomous.json').read_text())
    except (FileNotFoundError,ValueError):a={}
    if a.get('job_id')==job.get('id'):
        result['interview']=a
        result['message']=a.get('message')
    return result
def state():
    with LOCK:return [public(j) for j in JOBS.values()][-30:]
def active():
    with LOCK:return any(j['status'] in ('running','stopping') for j in JOBS.values())
def start(action,options):
    cmd,channel=command_for(action,options)
    with LOCK:
        if active():raise RuntimeError('Другой запуск ещё выполняется')
        job_id=uuid.uuid4().hex
        logfile=BASE/'logs'/('operation-'+job_id+'.log');logfile.parent.mkdir(exist_ok=True)
        with logfile.open('w') as log:
            logfile.chmod(0o600)
            argv=python_command('-u',*cmd)
            if action=='giga-web' and options.get('autonomous') is True:argv=['/usr/bin/caffeinate','-i',*argv]
            process=subprocess.Popen(argv,cwd=BASE,stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True,env={**os.environ,'BOT_JOB_ID':job_id})
        job={'id':job_id,'action':action,'channel':channel,'mode':options.get('mode','preview'),'status':'running','started_at':time.time(),'pid':process.pid,'process':process,'options':options}
        JOBS[job_id]=job;save_json(BASE/'.state/jobs'/(job_id+'.json'),public(job))
        threading.Thread(target=_wait,args=(job_id,),daemon=True).start()
        return public(job)
def _wait(job_id):
    job=JOBS[job_id];code=job['process'].wait()
    with LOCK:
        job.update(status='stopped' if job['status']=='stopping' else 'completed' if code==0 else 'failed',returncode=code,finished_at=time.time())
        if code==20:job['status']='needs_attention'
        save_json(BASE/'.state/jobs'/(job_id+'.json'),public(job))
def stop(job_id):
    with LOCK:
        job=JOBS.get(job_id)
        if not job or job['status'] not in ('running','stopping'):raise ValueError('Нет выполняющегося запуска')
        job['status']='stopping';os.killpg(job['process'].pid,signal.SIGINT)
        threading.Thread(target=_terminate,args=(job_id,),daemon=True).start()
        return public(job)
def _terminate(job_id):
    job=JOBS[job_id]
    try:job['process'].wait(timeout=10)
    except subprocess.TimeoutExpired:
        with LOCK:
            if job['process'].poll() is None:os.killpg(job['process'].pid,signal.SIGTERM)
def log_tail(job_id):
    if job_id not in JOBS:raise ValueError('Неизвестный запуск')
    p=BASE/'logs'/('operation-'+job_id+'.log')
    with p.open('rb') as f:f.seek(max(0,p.stat().st_size-16000));s=f.read().decode('utf-8',errors='replace')
    s=re.sub(r'https://(?:[a-z]+\.)?hh\.ru/account/captcha[^\s\x1b]+','[капча: открой проверку кнопкой в панели]',s)
    s=re.sub(r'/start\s+[A-Za-z0-9_-]+','/start [параметр скрыт]',s)
    s=re.sub(r'(?i)(bearer\s+)[^\s]+',r'\1[скрыто]',s)
    s=re.sub(r'(?i)((?:access_token|refresh_token|api_hash|authorization)[\s\"\':=]+)[^\s,}]+',r'\1[скрыто]',s)
    return s


def shutdown():
    with LOCK:
        for job in JOBS.values():
            if job['status']=='running' and job['process'].poll() is None:
                job['status']='stopping'
                try:os.killpg(job['process'].pid,signal.SIGINT)
                except ProcessLookupError:pass
import atexit
atexit.register(shutdown)
