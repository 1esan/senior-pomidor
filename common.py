from pathlib import Path
import os, json

BASE = Path(__file__).resolve().parent
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(BASE / '.browsers')
HH_CONFIG = BASE / '.state' / 'hh'
HH_CONFIG.mkdir(parents=True, exist_ok=True, mode=0o700)

def hh_tool():
    from hh_applicant_tool.tool import HHApplicantTool
    from functools import partial
    tool=HHApplicantTool(config_dir=HH_CONFIG)
    tool.api_client.session.request=partial(tool.api_client.session.request,timeout=(10,45))
    tool.api_client.captcha_handler=None
    tool.api_client.max_retries=1
    tool.api_client.delay=max(tool.api_client.delay,1.0)
    if os.environ.get('BOT_JOB_ID'):
        from hh_captcha import install
        install(tool.api_client,BASE,os.environ['BOT_JOB_ID'])
    return tool

def write_status(channel, value):
    target = BASE / '.state' / 'auth_status' / f'{channel}.json'
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.chmod(0o600)
    temporary.replace(target)

def auth_status(channel):
    target = BASE / '.state' / 'auth_status' / f'{channel}.json'
    try: return json.loads(target.read_text())
    except (FileNotFoundError, ValueError): return {'status': 'not_connected'}


_hh_reader = None

def hh_read_json(path):
    """Чтение через рабочий API-клиент: certifi и обновление собственного токена."""
    from urllib.parse import urlsplit, parse_qs
    global _hh_reader
    parts = urlsplit(path)
    if parts.scheme or parts.netloc or not parts.path.startswith("/"):
        raise ValueError("Разрешены только относительные пути HH API")
    if _hh_reader is None:
        _hh_reader = hh_tool()
        _hh_reader.api_client.captcha_handler = None  # Капча только вручную.
    params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parts.query).items()}
    try:
        return _hh_reader.api_client.get(parts.path, params)
    finally:
        if _hh_reader.save_token():
            _hh_reader.auth_config._path.chmod(0o600)


def hh_urlopen(request, timeout=40):
    """Сертификаты certifi для вспомогательных urllib-клиентов на Mac."""
    import ssl, certifi, urllib.request
    url = request.full_url if hasattr(request, "full_url") else str(request)
    if not url.startswith("https://api.hh.ru/"):
        raise ValueError("Разрешён только официальный HH API")
    return urllib.request.urlopen(request, timeout=timeout,
                                  context=ssl.create_default_context(cafile=certifi.where()))


def hh_exchange(method,path,form=None):
    """Official client + refresh, mandatory contact guard and persistent send intent."""
    from urllib.parse import urlsplit,parse_qs
    from employer_guard import guard_negotiation,ContactBlocked
    from runtime import save_json
    import hashlib,re,time
    from hh_applicant_tool.api.errors import ApiError
    parts=urlsplit(path);method=method.upper()
    if parts.scheme or parts.netloc or not parts.path.startswith('/') or method not in ('GET','POST','DELETE'):
        raise ValueError('Недопустимый HH запрос')
    if method=='GET':return 200,hh_read_json(path)
    match=re.fullmatch(r'/negotiations/(\d+)(/messages)?',parts.path)
    if not match or method=='POST' and not match[2]:raise ContactBlocked('Неподдерживаемый путь контакта')
    guard_negotiation(match[1],lambda verb,url:hh_exchange(verb,url))
    tool=hh_tool();tool.api_client.captcha_handler=None;tool.api_client.max_retries=1
    state_path=BASE/'.state/outgoing-helper.json'
    try:state=json.loads(state_path.read_text())
    except FileNotFoundError:state={}
    ident=hashlib.sha256(json.dumps([method,parts.path,form],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if ident in state:raise ContactBlocked('Это действие уже выполнено либо требует проверки после прерывания; повтор остановлен')
    state[ident]={'path':parts.path,'status':'attempting','at':time.time()};save_json(state_path,state)
    statuses=[]
    def capture(response,*a,**kw):
        if response.url.split('?')[0]=='https://api.hh.ru'+parts.path:statuses.append(response.status_code)
    tool.api_client.session.hooks.setdefault('response',[]).append(capture)
    try:
        data=tool.api_client.request(method,parts.path,form or {})
        code=statuses[-1] if statuses else 0
        state[ident].update(status='sent' if 200<=code<300 else 'unknown',http_status=code);save_json(state_path,state)
        return code,data
    except ApiError as e:
        state[ident].update(status='failed',http_status=e.status_code);save_json(state_path,state)
        return e.status_code,e.data
    finally:
        if tool.save_token():tool.auth_config._path.chmod(0o600)
