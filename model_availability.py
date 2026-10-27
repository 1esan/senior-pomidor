"""Retry only text generation; never repeat HH submissions."""
import os,time,re
from pathlib import Path
import requests
from model_retry import failure

class ModelUnavailable(RuntimeError):pass

def wait_for_generation(request, *, max_wait=None, clock=time.monotonic, sleep=time.sleep, report=None):
    job=os.environ.get('BOT_JOB_ID')
    limit=900 if job else 60
    if max_wait is not None:limit=max_wait
    started=clock();attempt=0;last_code="network_error"
    def state(status,code,message,delay=0):
        value={'job_id':job,'status':status,'code':code,'message':message,'next_retry_at':time.time()+delay if delay else None}
        if report:report(value)
        elif job:
            from common import BASE
            from runtime import save_json
            save_json(BASE/'.state/ai-wait.json',value)
    while True:
        if attempt and clock()-started>=limit:
            state('needs_attention',last_code,'Luna недоступна; текущая анкета сохранена')
            raise ModelUnavailable('Ожидание Luna завершено; текущая анкета сохранена')
        attempt+=1
        try:
            response=request()
            if response.status_code<400:
                if attempt>1:
                    state('resolved','ok','Luna снова доступна; продолжаю текущий вопрос')
                    print('AI_RECOVERED: продолжаю текущую генерацию',flush=True)
                return response
            code,retry,reason=failure(response)
        except (requests.ConnectionError,requests.Timeout):
            code,retry,reason='network_error',True,'Не удалось связаться с Luna'
        except requests.RequestException:
            code,retry,reason='request_error',False,'Запрос к Luna не выполнен'
        last_code=code
        print(f'AI_FAILURE: attempt={attempt} code={code} retryable={retry}',flush=True)
        if not retry:
            state('needs_attention',code,reason)
            raise ModelUnavailable(f'{reason}; код {code}. Текущая анкета сохранена, отправки не выполнялись')
        delay=[5,15,30][attempt-1] if attempt<=3 else 60
        remaining=limit-(clock()-started)
        if remaining<=0 or (not job and attempt>=3):
            state('needs_attention',code,'Luna недоступна; текущая анкета сохранена')
            raise ModelUnavailable(f'Luna недоступна; код {code}. Ожидание завершено, текущая анкета сохранена')
        delay=min(delay,remaining)
        message=f'Luna временно недоступна ({code}); повтор этого вопроса через {delay:g} сек.'
        state('waiting',code,message,delay)
        print('AI_WAIT: '+message,flush=True)
        until=clock()+delay
        while clock()<until:sleep(min(1,until-clock()))
