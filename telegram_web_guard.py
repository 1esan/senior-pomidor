"""Fail closed: a browser session is bound to one numerical Telegram peer."""
import time,logging,json,weakref
from autonomous_runtime import NeedsDecision

class QuestionChanged(NeedsDecision):
    """Question guard rejected before a send click; recipient failures stay fatal."""
    not_dispatched=True

TARGET_PEER='8491767152'
DOM_HELPER=r'''
const visible = e => !!e && e.isConnected && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
const current = () => {
  const inputs = [...document.querySelectorAll('.input-message-input[contenteditable="true"]')].filter(visible);
  if(inputs.length !== 1) return null;
  const editor=inputs[0], peer=editor.getAttribute('data-peer-id'), root=editor.closest('.chat');
  if(!peer || !root || !visible(root)) return null;
  return {editor,peer,root};
};
const routeIsTarget = raw => {
  const s=window.__candidateBotScope;
  if(!s) return false;
  try {
    const parsed=new URL(raw,location.href);
    if(parsed.origin!==s.origin || parsed.pathname!==s.pathname) return false;
    const route=decodeURIComponent(parsed.hash.slice(1)).split(/[?&]/)[0];
    return route===s.peer || route.toLowerCase()==='@giga_recruiter_bot' ||
      (s.fixtureEmptyRoute && !route);
  } catch {return false;}
};
const safeLocation = raw => {
  try {
    const parsed=new URL(raw,location.href);
    const route=decodeURIComponent(parsed.hash.slice(1)).split(/[?&]/)[0];
    return parsed.origin+parsed.pathname+(route===window.__candidateBotScope?.peer ? '#'+route : route.toLowerCase()==='@giga_recruiter_bot' ? '#@Giga_recruiter_bot' : route ? '#[other-route]' : '');
  } catch {return '[invalid-location]';}
};
const checked = () => {
  const s=window.__candidateBotScope, c=current();
  if(s && !routeIsTarget(location.href)) {s.latched=true;s.reason='navigation route does not identify the verified bot';}
  if(!s || s.latched || !c || c.peer!==s.peer || Date.now()/1000>=s.expires) throw new Error(s?.reason || (!c ? 'composer unavailable' : c.peer!==s?.peer ? 'foreign peer' : 'scope unavailable or expired'));
  return c;
};
'''
BOOT_JS='arg => {'+DOM_HELPER+r'''
const c=current();
if(!c || c.peer!==arg.peer) return {ok:false,reason:'Открыт другой чат или адресат не подтверждён'};
if(window.__candidateBotScope) return {ok:false,reason:'Страница уже привязана к запуску'};
const s=window.__candidateBotScope={peer:arg.peer,expires:arg.expires,latched:false,
  origin:location.origin,pathname:location.pathname,
  fixtureEmptyRoute:location.protocol==='about:' && !location.hash,
  lastLocation:location.href,lastPeer:c.peer,navigation:[],navigationSeq:0};
if(!routeIsTarget(location.href)) {s.latched=true;s.reason='initial route does not identify the verified bot';return {ok:false,reason:s.reason};}
const watch=records=>{const now=current();if(!now || now.peer!==s.peer) {s.latched=true;s.reason=!now?'composer disappeared or ambiguous':'foreign visible peer';} for(const r of records||[]) if(r.type==="attributes" && r.attributeName==="data-peer-id" && r.target.classList.contains("input-message-input") && r.oldValue && r.oldValue!==s.peer) {s.latched=true;s.reason='peer attribute changed from another recipient';}};
new MutationObserver(watch).observe(document.body,{subtree:true,childList:true,attributes:true,attributeOldValue:true,attributeFilter:['data-peer-id','class','style','hidden']});
const navigation = event => {
  const before=event.oldURL || s.lastLocation;
  const after=event.newURL || location.href;
  const now=current();
  const sameTarget=routeIsTarget(before) && routeIsTarget(after) && routeIsTarget(location.href) && now?.peer===s.peer;
  const allowed=!s.latched && sameTarget && Date.now()/1000<s.expires;
  const record={seq:++s.navigationSeq,event:event.type,before:safeLocation(before),after:safeLocation(after),peer_before:s.lastPeer,peer_after:now?.peer||null,allowed};
  s.navigation.push(record);if(s.navigation.length>10)s.navigation.shift();
  s.lastLocation=location.href;s.lastPeer=now?.peer||null;
  if(!allowed) {s.latched=true;s.reason=s.reason || 'navigation changed recipient, route, or verified composer';}
};
window.addEventListener('hashchange',navigation);
window.addEventListener('popstate',navigation);
window.addEventListener('unhandledrejection',e=>{const reason=e.reason;const type=reason?.type||reason?.originalError?.error_message;if(s.awaitingCallback&&type==='BOT_RESPONSE_TIMEOUT')s.callbackError='BOT_RESPONSE_TIMEOUT';});
return {ok:true,peer:c.peer};
}'''
CHECK_JS='() => {'+DOM_HELPER+r'''
try {const c=checked();return {ok:true,peer:c.peer,navigation:window.__candidateBotScope?.navigation||[]};} catch(e) {return {ok:false,reason:String(e.message),navigation:window.__candidateBotScope?.navigation||[]};}
}'''
QUESTION_HELPER="\nconst questionIsCurrent = (c,arg) => {\n  const bubbles=[...c.root.querySelectorAll('.bubbles .bubble')].filter(b=>b.classList.contains('is-in')||b.classList.contains('is-out'));\n  const last=bubbles[bubbles.length-1];\n  const recoveryOutgoing=arg.recovery===true && arg.text==='/change_vacancy' && arg.source_direction==='out';\n  if(!last || !last.classList.contains(recoveryOutgoing?'is-out':'is-in') || (last.dataset.mid||last.querySelector('[data-mid]')?.getAttribute('data-mid'))!==arg.mid) throw new Error('Question already answered or changed');\n  const msg=last.querySelector('.message');if(!msg) throw new Error('Question unavailable');\n  const clone=msg.cloneNode(true);clone.querySelectorAll('.time,.reactions,.reply-markup').forEach(e=>e.remove());\n  if(clone.innerText.trim()!==arg.source_text.trim()) throw new Error('Question text changed');\n};\n"
SEND_JS='arg => {'+DOM_HELPER+QUESTION_HELPER+r'''
try {
  const c=checked();questionIsCurrent(c,arg);
  if(c.editor.innerText.trim()!==arg.text.trim()) throw new Error('Prepared text changed');
  const buttons=[...c.root.querySelectorAll('.btn-send')].filter(visible);
  if(buttons.length!==1 || !buttons[0].classList.contains('send') || buttons[0].disabled) throw new Error('Send button unavailable or has another action');
  checked();
  // Validation and dispatch occur in one JS task; no global keyboard/focus input.
  buttons[0].click();
  return {ok:true,peer:c.peer};
}catch(e){return {ok:false,reason:String(e.message)};}
}'''
BUTTON_JS='arg => {'+DOM_HELPER+QUESTION_HELPER+r'''
try {
  const c=checked();questionIsCurrent(c,arg);
  const source=[...c.root.querySelectorAll('.bubbles .bubble')].filter(b=>visible(b)&&(b.dataset.mid||b.querySelector('[data-mid]')?.getAttribute('data-mid'))===arg.mid);if(source.length!==1)throw new Error('Current question bubble missing or ambiguous');const matches=[...source[0].querySelectorAll('.reply-markup-button')].filter(b=>visible(b)&&b.innerText.trim()===arg.label);
  if(!matches.length) throw new Error('Interview button unavailable');
  const b=matches[matches.length-1];
  if(b.tagName==='A' || b.closest('a') || b.querySelector('a') || b.hasAttribute('href')) throw new Error('URL buttons require user');
  checked();
  // WebK selects click or mousedown depending on device capabilities.
  // Keep both events in the same task with target/question checks between them.
  b.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true,button:0,buttons:1,detail:1}));
  checked();questionIsCurrent(c,arg);
  b.dispatchEvent(new MouseEvent('mouseup',{bubbles:true,cancelable:true,button:0,buttons:0,detail:1}));
  checked();questionIsCurrent(c,arg);
  b.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,button:0,buttons:0,detail:1}));
  return {ok:true,peer:c.peer};
}catch(e){return {ok:false,reason:String(e.message)};}
}'''
def check_deadline(expires,now=None):
    if expires is None or (time.time() if now is None else now)>=expires:
        raise NeedsDecision('Срок запуска истёк; автоматическая отправка остановлена')
async def bind_page(page,expires):
    r=await page.evaluate(BOOT_JS,{'peer':TARGET_PEER,'expires':expires})
    if not r.get('ok'):raise NeedsDecision(r.get('reason','Адресат не подтверждён'))
_navigation_seen=weakref.WeakKeyDictionary()
async def assert_target(page):
    r=await page.evaluate(CHECK_JS)
    seen=_navigation_seen.get(page,0)
    for event in r.get('navigation',[]):
        if event['seq']>seen:
            logging.getLogger('telegram-guard').info('TELEGRAM_NAVIGATION: %s',json.dumps(event,ensure_ascii=False))
            seen=event['seq']
    _navigation_seen[page]=seen
    if not r.get('ok'):raise NeedsDecision('Отправка остановлена: '+r.get('reason','чат изменился или срок истёк'))
    return r['peer']
async def dispatch(page,script,arg):
    r=await page.evaluate(script,arg)
    if not r.get('ok'):
        reason=r.get('reason','адресат не подтверждён')
        if script==SEND_JS and reason in ('Question already answered or changed','Question text changed'):
            raise QuestionChanged('Отправка остановлена: '+reason)
        raise NeedsDecision('Отправка остановлена: '+reason)
    return r['peer']

async def require_empty_editor(page):
    value=await page.evaluate('() => {'+DOM_HELPER+'return checked().editor.innerText.trim();}')
    if value:raise NeedsDecision('В поле уже есть черновик пользователя; отправка остановлена')

ARM_BUTTON_JS='arg => {'+DOM_HELPER+QUESTION_HELPER+r"""
try {
 const c=checked();questionIsCurrent(c,arg);
 const source=[...c.root.querySelectorAll('.bubbles .bubble')].filter(b=>visible(b)&&(b.dataset.mid||b.querySelector('[data-mid]')?.getAttribute('data-mid'))===arg.mid);if(source.length!==1)throw new Error('Current question bubble missing or ambiguous');const matches=[...source[0].querySelectorAll('.reply-markup-button')].filter(b=>visible(b)&&b.innerText.trim()===arg.label);
 if(matches.length!==1) throw new Error('Button missing or ambiguous');
 const b=matches[0];if(b.tagName==='A'||b.closest('a')||b.querySelector('a')||b.hasAttribute('href')) throw new Error('URL button requires user');
 b.setAttribute('data-candidate-action',arg.token);window.__candidateBotScope.callbackError=null;window.__candidateBotScope.awaitingCallback=true;
 const stop=e=>{const target=e.target?.closest?.('.reply-markup-button');if(!target)return;
  try {const now=checked();questionIsCurrent(now,arg);if(target!==b||!visible(b)||b.closest('.chat')!==now.root)throw new Error('Action target changed');}
  catch(error){e.preventDefault();e.stopImmediatePropagation();window.__candidateNativeError=String(error.message);}
 };
 const events=['pointerdown','mousedown','pointerup','mouseup','click'];events.forEach(t=>document.addEventListener(t,stop,true));
 window.__candidateNativeAction={token:arg.token,b,stop,events};window.__candidateNativeError=null;
 return {ok:true};
}catch(e){return {ok:false,reason:String(e.message)};}
}"""
DISARM_BUTTON_JS='token => {const a=window.__candidateNativeAction;if(a?.token!==token)return; a.events.forEach(t=>document.removeEventListener(t,a.stop,true));a.b.removeAttribute("data-candidate-action");window.__candidateNativeAction=null;return window.__candidateNativeError;}'
async def native_button(page,label,question):
    import secrets
    token=secrets.token_hex(16)
    result=await page.evaluate(ARM_BUTTON_JS,{'token':token,'label':label,**question})
    if not result.get('ok'):
        reason=result.get('reason','')
        error_type=QuestionChanged if reason in ('Question already answered or changed','Question text changed') else NeedsDecision
        error=error_type('Кнопка не подтверждена: '+reason);error.not_dispatched=True;raise error
    try:
        await page.locator('[data-candidate-action="'+token+'"]').click(timeout=5000)
    finally:
        error=await page.evaluate(DISARM_BUTTON_JS,token)
    if error:raise NeedsDecision('Нажатие заблокировано: '+error)
