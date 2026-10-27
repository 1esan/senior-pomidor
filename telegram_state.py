import hashlib,json,re
from common import BASE,hh_read_json
from runtime import save_json
from employer_guard import ensure_contact,extract_company,ContactBlocked

def fingerprint(bubble):
    return (str(bubble.get('peer_id'))+':' if bubble.get('peer_id') else '')+str(bubble['mid'])+':'+hashlib.sha256(json.dumps([bubble.get('text'),bubble.get('buttons')],ensure_ascii=False).encode()).hexdigest()[:16]
def load_state(transport,dry):
    path=BASE/'.state/telegram-progress'/(transport+('-preview' if dry else '-live')+'.json')
    try:state=json.loads(path.read_text())
    except FileNotFoundError:state={'handled':[],'done':[],'current':{},'actions':{}}
    return path,state
def begin_action(path,state,key):
    if key in state['actions']:raise RuntimeError('Это действие уже отправлено или имеет неопределённый результат. Автоповтор запрещён; проверь чат вручную')
    state['actions'][key]='attempting';save_json(path,state)
def finish_action(path,state,key):
    state['actions'][key]='submitted';save_json(path,state)
def resolve_company(text):
    explicit=extract_company(text)
    if explicit:return explicit
    match=re.search(r'https?://(?:[a-z]+\.)?hh\.ru/vacancy/(\d+)',text or '',re.I)
    if match:
        full=hh_read_json('/vacancies/'+match.group(1));ensure_contact(full)
        return (full.get('employer') or {}).get('name')
    try:mapping=json.loads((BASE/'.state/telegram-bindings.json').read_text())
    except FileNotFoundError:return None
    label=re.sub(r'^\s*\d+[.)]\s*','',text or '').strip().casefold()
    target=mapping.get(label)
    if target:
        full=hh_read_json('/vacancies/'+target['vacancy_id']);ensure_contact(full)
        if str((full.get('employer') or {}).get('id'))!=target['employer_id']:raise ContactBlocked('Работодатель привязанной вакансии изменился')
        return (full.get('employer') or {}).get('name')
    return None
def bind(label,vacancy_id,confirmed):
    if confirmed is not True:raise ValueError('Подтвердите, что это одна и та же вакансия')
    if not isinstance(label,str) or not 5<=len(label.strip())<=500 or not str(vacancy_id).isdigit():raise ValueError('Нужны точная подпись вакансии и HH ID')
    full=hh_read_json('/vacancies/'+str(vacancy_id));ensure_contact(full)
    if str(full.get('id'))!=str(vacancy_id):raise ValueError('ID не подтверждён')
    path=BASE/'.state/telegram-bindings.json'
    try:mapping=json.loads(path.read_text())
    except FileNotFoundError:mapping={}
    k=re.sub(r'^\s*\d+[.)]\s*','',label).strip().casefold()
    target={'vacancy_id':str(vacancy_id),'employer_id':str(full['employer']['id']),'company':full['employer']['name'],'title':full['name']}
    mapping[k]=target;save_json(path,mapping);return target


def verified_bound_scope(label):
    """Only user-confirmed menu bindings with an accepted HH application."""
    mapping=json.loads((BASE/'.state/telegram-bindings.json').read_text())
    key=re.sub(r'^\s*\d+[.)]\s*','',label).strip().casefold()
    target=mapping.get(key)
    if not target:raise ContactBlocked('Нет проверенной привязки следующей вакансии')
    vid=str(target['vacancy_id'])
    intents_path=BASE/'.state/hh/application-intents.json'
    intents=json.loads(intents_path.read_text()) if intents_path.exists() else {}
    accepted=intents.get(vid,{}).get('status')=='sent'
    if not accepted:
        for file in (BASE/'.state/batches').glob('*/dispatch.json'):
            if any(str(r.get('vacancy_id'))==vid and r.get('status') in ('accepted','verified') for r in json.loads(file.read_text()).get('results',[])):
                accepted=True;break
    if not accepted:raise ContactBlocked('Нет подтверждённого отклика на следующую вакансию')
    v=hh_read_json('/vacancies/'+vid);ensure_contact(v)
    if str(v['employer']['id'])!=target['employer_id']:raise ContactBlocked('Работодатель привязанной вакансии изменился')
    return {'id':vid,'name':v['name'],'company':v['employer']['name'],'employer_id':str(v['employer']['id'])}
