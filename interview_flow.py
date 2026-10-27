"""Persistent interview conversation and explicit completion signals."""
import re

def closing_reply(text):
    return bool(re.search(r'(?:других|больше|пока|дополнительных).{0,20}вопросов.{0,12}нет|вопросов нет',text,re.I))

def history_key(current):
    vid=current.get('vacancy_id') or current.get('id')
    return 'hh:'+str(vid) if vid else str(current.get('company') or '')+'::'+str(current.get('name') or '')

def dialogue_guidance(history):
    answers=[x['content'] for x in history if x.get('role')=='assistant']
    if not answers:return ''
    repeated=sum(bool(re.search(r'головн.{0,15}модел|субагент|оркестрац',a,re.I)) for a in answers)
    instruction='Учитывай уже сказанное в этом интервью. Не пересказывай заново вступление и один и тот же кейс. Отвечай сразу на новый вопрос, добавляя только новые детали. Не повторяй условное «я бы» в каждом предложении: для общего подхода используй настоящее время, сохраняя различие между реальным опытом и предлагаемым решением.'
    if repeated:instruction+=' Пример оркестрации сабагентов уже был: не начинай с него снова. Для RAG, Evals и токенов объясни конкретно поиск, проверку качества или ограничения; не приписывай отсутствующие внедрения.'
    return instruction


def activate_context(state,current):
    """Keep only the active interview; completed conversations never enter prompts."""
    key=history_key(current)
    state.pop('histories',None)  # Legacy title-based histories are ambiguous.
    active=state.get('active_context',{})
    history=active.get('messages',[]) if active.get('key')==key and key not in state.get('completed_interviews',{}) else []
    state['active_context']={'key':key,'messages':list(history)}
    return list(history)


def complete_context(state,current):
    key=history_key(current)
    state.setdefault('completed_interviews',{})[key]={
        'vacancy_id':current.get('vacancy_id') or current.get('id'),
        'name':current.get('name'),'company':current.get('company'),
        'completed_at':__import__('time').time(),'intro_fingerprint':current.get('intro_fingerprint')}
    state.pop('histories',None)
    state['active_context']={}


def next_verified_menu(base,buttons,bubble,state,verify,target_for,preferred=None):
    """Match locally first, then freshly verify the actual application/invitation."""
    import json
    candidates=[]
    if preferred:candidates.append(preferred)
    for path in sorted((base/'.state/giga-menu-identities').glob('*.json')):
        identity=json.loads(path.read_text())
        candidates.append({'id':identity['vacancy_id'],'menu_identity':identity})
    bindings=base/'.state/telegram-bindings.json'
    if bindings.exists():
        candidates.extend({'id':v['vacancy_id'],'name':v['title'],'employer_id':v['employer_id']} for v in json.loads(bindings.read_text()).values())
    seen=set();skipped=[]
    from autonomous_runtime import NeedsDecision
    from employer_guard import ContactBlocked
    for candidate in candidates:
        vid=str(candidate['id'])
        if vid in seen or 'hh:'+vid in state.get('completed_interviews',{}):continue
        seen.add(vid)
        try:
            target_for(buttons,candidate,bubble)
            scope=verify(vid)
            target=target_for(buttons,scope,bubble)
            return scope,target,skipped
        except (NeedsDecision,ContactBlocked) as exc:
            skipped.append({'vacancy_id':vid,'reason':str(exc)})
    return None,None,skipped


def should_handle_message(fingerprint,handled,*,first,menu,auto_next,autonomous):
    # Menu inspection may be repeated on startup; durable dispatch keys still
    # prevent repeating an uncertain click on that menu.
    return fingerprint not in handled or first and menu and (auto_next or autonomous)


def waiting_for_recruiter(text):
    normalized=' '.join(text.casefold().split())
    return 'спасибо за выбор вакансии' in normalized and ('несколько секунд' in normalized or 'начнем диалог' in normalized or 'начнём диалог' in normalized)


def rating_request(bubble):
    buttons=bubble.get('buttons',[])
    return bool(buttons) and all(__import__('re').fullmatch(r'[★☆⭐\s]+',b) for b in buttons)


def menu_page_key(bubble):
    import hashlib,json
    return hashlib.sha256(json.dumps([bubble.get('text'),bubble.get('buttons'),bubble.get('section_links')],ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]


def migrate_context(state,path):
    """Quarantine pre-fix history; do not replay or silently erase completion marks."""
    if state.get('context_schema')==2:return
    from runtime import save_json
    from pathlib import Path
    if state.get('active_context') or state.get('histories'):
        backup=Path(path).parent/(Path(path).stem+'-legacy-context.json')
        if not backup.exists():save_json(backup,{'active_context':state.get('active_context'),'histories':state.get('histories'),'current':state.get('current')})
    state.update(context_schema=2,active_context={},current={},awaiting_menu=False)
    state.pop('histories',None)
    # Old completions remain excluded to avoid repeating interviews, but are
    # explicitly distinguished from new completions with a verified intro.
    for record in state.get('completed_interviews',{}).values():
        if not record.get('intro_fingerprint'):record['legacy_identity_unverified']=True
    save_json(path,state)


def terminal_notices(bubbles,handled,current):
    from autonomous_runtime import interview_finished
    intro_mid=current.get('intro_mid')
    if not intro_mid:return []
    def after(mid):
        try:return int(mid)>int(intro_mid)
        except (TypeError,ValueError):return False
    from telegram_state import fingerprint
    return [bubble for bubble in bubbles[:-1] if bubble.get('dir')=='in' and after(bubble.get('mid')) and fingerprint(bubble) not in handled and (interview_finished(bubble.get('text','')) or rating_request(bubble))]
