"""Independent interview runtime: verified scope, model service and observable status."""
import json,os,re,subprocess,time,html
from urllib.parse import urlsplit,parse_qs
from pathlib import Path
import requests
from common import BASE,hh_read_json
from employer_guard import ensure_contact,ContactBlocked
from runtime import save_json
from adapter_config import adapter_dir,adapter_key,node_command,AdapterConfigurationError

STATE=BASE/'.state/giga-autonomous.json'
class NeedsDecision(RuntimeError):pass

def status(value,**fields):
    try:previous=json.loads(STATE.read_text())
    except FileNotFoundError:previous={}
    if previous.get('job_id')!=os.environ.get('BOT_JOB_ID'):previous={}
    previous.update(status=value,job_id=os.environ.get('BOT_JOB_ID'),pid=os.getpid(),updated_at=time.time(),**fields)
    save_json(STATE,previous)

def adapter_status():
    s=requests.Session();s.trust_env=False
    key=adapter_key()
    r=s.get('http://127.0.0.1:8766/api/status',headers={'Authorization':'Bearer '+key},timeout=3)
    r.raise_for_status();return r.json()

def ensure_adapter():
    try:d=adapter_status()
    except (requests.ConnectionError, AdapterConfigurationError):
        try:
            adapter=adapter_dir(); node=node_command()
            if not (adapter/'server.mjs').is_file():
                raise AdapterConfigurationError('В указанной папке не найден server.mjs адаптера ИИ.')
        except AdapterConfigurationError as exc:
            raise NeedsDecision(str(exc)) from exc
        log_path=BASE/'logs/luna-service.log'
        with log_path.open('a') as log:
            log_path.chmod(0o600)
            p=subprocess.Popen([node,'server.mjs'],cwd=adapter,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        save_json(BASE/'.state/services/luna.json',{'pid':p.pid,'started_at':time.time()})
        d={}
        for _ in range(30):
            time.sleep(1)
            try:d=adapter_status()
            except (requests.RequestException,AdapterConfigurationError):continue
            if d.get('sharing') and d.get('models'):break
            if p.poll() is not None:break
    if not d.get('sharing') or not any(m.get('slug')=='gpt-6-luna' for m in d.get('models',[])):
        raise NeedsDecision('Подписочный вход Luna недоступен; открой её панель подключения')

def invitation_links(messages):
    links=set()
    for message in messages:
        if (message.get('author') or {}).get('participant_type')!='employer':continue
        for raw in re.findall(r'https?://[^\s<>"\']+',html.unescape(message.get('text') or '')):
            url=raw.rstrip('.,);]')
            parts=urlsplit(url)
            if parts.scheme!='https' or parts.hostname not in ('t.me','telegram.me'):continue
            if parts.path.strip('/').casefold()!='giga_recruiter_bot':continue
            start=(parse_qs(parts.query).get('start') or [''])[0]
            if start and re.fullmatch(r'[A-Za-z0-9_-]+',start):links.add(url)
    return sorted(links)


def verified_scope(vacancy_id):
    vid=str(vacancy_id)
    if not vid.isdigit():raise ValueError('Нужен HH ID вакансии')
    v=hh_read_json('/vacancies/'+vid);ensure_contact(v)
    if str(v.get('id'))!=vid:raise NeedsDecision('HH вернул другую вакансию')
    employer_id=str(v['employer']['id'])
    negotiation=None
    for group in ('active','archived'):
        for page in range(50):
            result=hh_read_json(f'/negotiations?page={page}&per_page=100&status={group}')
            for item in result.get('items',[]):
                vacancy=item.get('vacancy') or {}
                if str(vacancy.get('id'))==vid:
                    if str((vacancy.get('employer') or {}).get('id'))!=employer_id:
                        raise NeedsDecision('Работодатель отклика не совпадает с выбранной вакансией')
                    negotiation=item;break
            if negotiation or page+1>=result.get('pages',1):break
        else:raise NeedsDecision('Выдача откликов слишком большая; проверка не завершена')
        if negotiation:break
    if not negotiation:raise NeedsDecision('В твоём аккаунте HH не найден отклик на выбранную вакансию')
    nid=str(negotiation['id']);links=set()
    for page in range(100):
        messages=hh_read_json(f'/negotiations/{nid}/messages?page={page}&per_page=100')
        links.update(invitation_links(messages.get('items',[])))
        if page+1>=messages.get('pages',1):break
    else:raise NeedsDecision('Переписка приглашения слишком большая; проверка не завершена')
    if not links:raise NeedsDecision('В переписке этой вакансии нет приглашения работодателя в ГигаРекрутёр')
    save_json(BASE/'.state/giga-invitations'/(vid+'.json'),{'vacancy_id':vid,'negotiation_id':nid,'employer_id':employer_id,'links':sorted(links),'verified_at':time.time()})
    scope={'id':vid,'name':v['name'],'company':v['employer']['name'],'employer_id':employer_id,'negotiation_id':nid,'description':html.unescape(re.sub('<[^>]+>',' ',v.get('description') or '')),'verified_at':time.time()}
    identity_path=BASE/'.state/giga-menu-identities'/(vid+'.json')
    if identity_path.exists():
        identity=json.loads(identity_path.read_text())
        description=html.unescape(re.sub('<[^>]+>',' ',v.get('description') or ''))
        normalize=lambda text:re.sub(r'\s+',' ',text).strip().casefold()
        if identity.get('vacancy_id')!=vid or identity.get('employer_id')!=employer_id or normalize(identity['hh_identity_phrase']) not in normalize(description):
            raise NeedsDecision('Описание или работодатель связанной вакансии изменились')
        scope['menu_identity']=identity
    return scope


def check_intro(bubbles,scope):
    intros=[b.get('text','') for b in bubbles if b.get('dir')=='in' and re.search(r'получил.*отклик.*позици',b.get('text',''),re.I|re.S)]
    if not intros or scope['name'].casefold() not in intros[-1].casefold():
        raise NeedsDecision('В текущем чате не подтверждена выбранная вакансия; автоматизация остановлена')

def fresh_guard(scope,current,context=''):
    if (current.get('vacancy_id') and str(current['vacancy_id'])!=str(scope['id'])) or current.get('name')!=scope['name'] or current.get('company')!=scope['company']:
        raise ContactBlocked('Контекст вакансии изменился; другая вакансия не разрешена этим запуском')
    from interview_settings import settings
    # Local exclusions are checked on every action even while HH is cached.
    ensure_contact({'id':scope['id'],'name':scope['name'],'employer':{'id':scope['employer_id'],'name':scope['company']}},context=context)
    if time.time()-scope.get('verified_at',0)<settings()['scope_cache_seconds']:return
    v=hh_read_json('/vacancies/'+scope['id']);ensure_contact(v,context=context)
    if str(v['employer']['id'])!=scope['employer_id']:raise ContactBlocked('Работодатель изменился')
    scope['verified_at']=time.time()

def interview_finished(text):
    text=text.casefold()
    strong=('спасибо за интервью','интервью завершено','благодарю за ответы','спасибо за ответы','на этом всё','спасибо, этого достаточно')
    weak=('передал команде','передам ваши ответы','спасибо за уделённое время','зафиксировал ваш опыт','этого достаточно')
    return any(s in text for s in strong) or '?' not in text and any(s in text for s in weak)

def requires_decision(text):
    return bool(re.search(r'обработк[а-я]* персональн|согласие на|(?:приня|подпис|подтверд)[а-я]*.{0,60}оффер|(?:выбер|подтверд|назнач|запиш)[а-я]*.{0,70}(?:врем|дат|встреч|созвон)|(?:когда|в какое время|какое время).{0,80}(?:созвон|встреч|собеседован)',text,re.I|re.S))
