"""A manual CAPTCHA gate. No requests are made until the user presses Resume."""
import os,time,json
from pathlib import Path
from urllib.parse import urlsplit
from runtime import save_json

class CaptchaWaitExpired(BaseException):pass

def read_state(base):
    try:return json.loads((Path(base)/'.state/hh-captcha.json').read_text())
    except FileNotFoundError:return {}

def valid_url(url):
    p=urlsplit(url or '')
    return p.scheme=='https' and (p.hostname=='hh.ru' or (p.hostname or '').endswith('.hh.ru')) and p.path=='/account/captcha'

def wait_for_user(base,url,job_id,clock=time.monotonic,sleep=time.sleep,max_wait=43200):
    if not valid_url(url):raise CaptchaWaitExpired('HH вернул неизвестный адрес проверки')
    path=Path(base)/'.state/hh-captcha.json'
    state={'status':'waiting','job_id':job_id,'url':url,'created_at':time.time(),'message':'hh.ru требует капчу. Открой проверку, пройди её и нажми «Продолжить».'}
    save_json(path,state)
    print('HH_CAPTCHA_WAIT: запросы приостановлены; пройди капчу и нажми «Продолжить» в панели',flush=True)
    deadline=clock()+max_wait
    try:
        while clock()<deadline:
            current=read_state(base)
            if current.get('job_id')!=job_id:raise CaptchaWaitExpired('Состояние проверки изменилось')
            if current.get('status')=='resume_requested':
                save_json(path,{**current,'status':'checking'})
                return
            sleep(.5)
        raise CaptchaWaitExpired('Время ожидания капчи истекло; выполненные отклики сохранены')
    except BaseException:
        save_json(path,{**state,'status':'stopped'})
        raise

def install(client,base,job_id):
    original=client.request
    def request(method,endpoint,*args,**kwargs):
        from hh_applicant_tool.api.errors import CaptchaRequired
        while True:
            try:
                result=original(method,endpoint,*args,**kwargs)
                current=read_state(base)
                if current.get('job_id')==job_id and current.get('status')=='checking':
                    save_json(Path(base)/'.state/hh-captcha.json',{**current,'status':'resolved','resolved_at':time.time()})
                    print('HH_CAPTCHA_RESOLVED: проверка принята, продолжаю с текущего запроса',flush=True)
                return result
            except CaptchaRequired as e:
                wait_for_user(base,e.captcha_url,job_id)
                # Only an explicit CAPTCHA rejection is retried. Network errors
                # and unknown POST outcomes are never retried by this gate.
    client.request=request
