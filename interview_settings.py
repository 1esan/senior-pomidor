"""One local configuration for interview timing and discovery."""
import json
from pathlib import Path
DEFAULTS={'post_interview_menu_wait_seconds':15,'model_retry_attempts':3,'model_retry_initial_seconds':5,'model_retry_max_seconds':10,'history_load_timeout_seconds':60,'history_stable_seconds':3,'poll_seconds':2,'reply_pause_min_seconds':60,'reply_pause_max_seconds':120,'menu_pause_min_seconds':5,'menu_pause_max_seconds':10,'scope_cache_seconds':900,'catalog_cache_seconds':300,'max_catalog_pages':50,'max_menu_pages':50,'recruiter_wait_seconds':360,'recovery_retry_seconds':600,'recovery_max_resets':3,'allowed_employer_ids':['3529']}
def settings():
    path=Path(__file__).parent/'interview_settings.json'
    value={**DEFAULTS,**(json.loads(path.read_text()) if path.exists() else {})}
    for key in DEFAULTS:
        if key=='allowed_employer_ids':
            if not isinstance(value[key],list) or not value[key] or any(not str(i).isdigit() for i in value[key]):raise ValueError('Неверный список работодателей интервью')
            value[key]=[str(i) for i in value[key]]
        elif not isinstance(value[key],(int,float)) or isinstance(value[key],bool) or not 0<value[key]<=86400:raise ValueError('Неверная настройка '+key)
    if not isinstance(value['model_retry_attempts'],int) or not 1<=value['model_retry_attempts']<=5:raise ValueError('Неверное число попыток Luna')
    if not isinstance(value['recovery_max_resets'],int) or not 1<=value['recovery_max_resets']<=10:raise ValueError('Неверное число восстановлений интервью')
    if value['model_retry_max_seconds']>60:raise ValueError('Пауза повторов Luna не должна превышать 60 секунд')
    if value['reply_pause_max_seconds']<value['reply_pause_min_seconds']:raise ValueError('Неверный диапазон паузы')
    return value
