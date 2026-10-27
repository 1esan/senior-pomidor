"""HH test XHR classification and manual CAPTCHA gate. No blind POST retries."""
import json,re,os,time
from pathlib import Path
from urllib.parse import urlsplit,urljoin,urlencode
import requests

class TestSubmissionBlocked(RuntimeError):pass

def classify(response):
    try:body=response.json()
    except (ValueError,TypeError):body={}
    body=body if isinstance(body,dict) else {}
    errors=body.get('errors') or []
    if not isinstance(errors,list):errors=[]
    codes=[]
    for item in errors:
        if isinstance(item,dict):
            value=item.get('type') or item.get('value') or item.get('code')
            if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}',value):codes.append(value)
    for key in ('error','code'):
        value=body.get(key)
        if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}',value):codes.append(value)
    captcha=body.get('hhcaptcha') or {}
    captcha=captcha if isinstance(captcha,dict) else {}
    url=next((x.get('captcha_url') for x in errors if isinstance(x,dict) and x.get('captcha_url')),None) or body.get('captcha_url')
    state=captcha.get('captchaState')
    if not url and isinstance(state,str) and state:
        url='https://hh.ru/account/captcha?'+urlencode({'state':state})
    location=response.headers.get('Location','')
    from hh_captcha import valid_url
    if not url and location:
        proposed=urljoin('https://hh.ru',location)
        if valid_url(proposed):url=proposed
    explicit_captcha=bool(state or 'captcha_required' in codes or url)
    # An HTTP 200 with a CAPTCHA object is still a rejected submission.
    if explicit_captcha:kind='captcha'
    elif response.status_code in (401,403) and (any('xsrf' in x or 'csrf' in x for x in codes)):kind='csrf'
    elif response.status_code==401 or '/login' in location or '/account/login' in location:kind='login'
    elif response.status_code==403:kind='forbidden'
    elif response.status_code>=400:kind='http_error'
    elif not (body.get('success') is True or body.get('success')=='true'):kind='unconfirmed'
    else:kind='accepted'
    return kind,body,url,{'http_status':response.status_code,'kind':kind,'error_codes':codes,
        'content_type':str(response.headers.get('Content-Type','')).split(';')[0][:80],
        'has_captcha_state':bool(state)}

def record_diagnostic(base,vid,diagnostic):
    from runtime import save_json
    safe={**diagnostic,'vacancy_id':str(vid),'at':time.time()}
    folder=Path(base)/'.state/test-http-diagnostics'
    save_json(folder/f'{vid}-{time.time_ns()}.json',safe)
    print(f'HH_TEST_HTTP: vacancy={vid} status={safe.get("http_status")} kind={safe.get("kind")} codes={safe.get("error_codes",[])}',flush=True)

def xhr_headers(xsrf,referer):
    if not isinstance(xsrf,str) or not xsrf:raise TestSubmissionBlocked('В сессии сайта HH нет _xsrf; войди в HH заново. Ответы теста сохранены')
    origin='https://hh.ru'
    p=urlsplit(referer)
    if p.scheme!='https' or p.hostname!='hh.ru':raise TestSubmissionBlocked('Неожиданный адрес формы теста')
    return {'Accept':'application/json','Origin':origin,'Referer':referer,'X-Requested-With':'XMLHttpRequest',
        'X-XSRFToken':xsrf,'X-Hhtmfrom':'vacancy','X-Hhtmsource':'vacancy_response'}

def submit_test(tool,vacancy,payload,referer,*,base,refresh,guard):
    vid=str(vacancy['id'])
    for attempt in range(3):
        guard()
        try:
            response=tool.session.post('https://hh.ru/applicant/vacancy_response/popup',data=payload,
                headers=xhr_headers(tool.xsrf_token,referer),timeout=(10,45),allow_redirects=False)
        except requests.RequestException as ex:
            record_diagnostic(base,vid,{'kind':'network_unknown','http_status':None,'error_codes':[],'exception_type':type(ex).__name__})
            # Read-only reconciliation; an uncertain POST is never repeated.
            try:
                fresh=tool.api_client.get('/vacancies/'+vid)
                relations=fresh.get('relations') if isinstance(fresh,dict) else None
                if isinstance(relations,list) and set(relations)&{'got_response','already_applied','got_invitation','got_rejection'}:
                    print(f'HH_TEST_RECONCILED: отклик {vid} подтверждён после сбоя сети, повтор не выполняется',flush=True)
                    return {'success':True,'reconciled':True}
            except Exception:pass
            raise TestSubmissionBlocked('HH не подтвердил отправку теста из-за сбоя сети. Ответы сохранены; повтор заблокирован до сверки отклика') from ex
        kind,body,url,diagnostic=classify(response)
        record_diagnostic(base,vid,diagnostic)
        if kind=='accepted':return body
        if kind=='captcha':
            from hh_captcha import valid_url,wait_for_user
            job=os.environ.get('BOT_JOB_ID')
            if not job or not valid_url(url) or attempt>=2:
                raise TestSubmissionBlocked('HH требует ручную проверку теста; ответы сохранены, повтор без проверки не выполняется')
            wait_for_user(base,url,job)
            # Only a known CAPTCHA rejection permits this path. Reconcile and refresh first.
            fresh=tool.api_client.get('/vacancies/'+vid)
            relations=fresh.get('relations') or []
            if set(relations)&{'got_response','already_applied','got_invitation','got_rejection'}:
                print(f'HH_TEST_RECONCILED: отклик {vid} уже существует, повтор не выполняется',flush=True)
                return {'success':True,'reconciled':True}
            payload=refresh(payload)
            continue
        messages={'csrf':'HH отклонил проверку сессии (CSRF); требуется повторный вход',
            'login':'Сайт HH требует повторного входа',
            'forbidden':'Сайт HH отклонил отправку теста (403), явного признака капчи нет',
            'http_error':f'HH вернул HTTP {response.status_code} при отправке теста',
            'unconfirmed':'HH не подтвердил приём ответов теста'}
        raise TestSubmissionBlocked(messages[kind]+'. Ответы сохранены; повтор заблокирован до сверки отклика')
    raise TestSubmissionBlocked('Проверка HH не завершена')
