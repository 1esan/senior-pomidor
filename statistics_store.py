"""Единственный публикуемый источник статистики для всех интерфейсов."""
import json, re, fcntl
from pathlib import Path
from datetime import datetime, timezone
from runtime import save_json

SECTIONS={'dashboard','activity','analysis','pdf','latest_run'}

def read_statistics(base):
    path=Path(base)/'statistics.json'
    if not path.exists():return {'schema_version':1,'revision':0}
    data=json.loads(path.read_text())
    if data.get('schema_version')!=1:raise ValueError('Неизвестная схема статистики')
    return data

def publish(base,section,value):
    if section not in SECTIONS:raise ValueError('Неизвестный раздел статистики')
    if section=='dashboard':
        f=value['funnel']
        if any(not isinstance(f[k],int) or f[k]<0 for k in ('sent','invited','rejected','pending','other')):raise ValueError('Некорректные счётчики')
        if f['sent']!=sum(f[k] for k in ('invited','rejected','pending','other')):raise ValueError('Воронка не сходится')
    folder=Path(base)/'.state';folder.mkdir(parents=True,exist_ok=True)
    with (folder/'statistics.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        data=read_statistics(base);data[section]=value
        data['revision']=data.get('revision',0)+1
        data['updated_at']=datetime.now(timezone.utc).isoformat()
        save_json(Path(base)/'statistics.json',data)
        return data

def render_report(base,name,source=None,export=False):
    data=read_statistics(base)
    section={'dashboard':'dashboard','activity':'activity'}[name]
    if not data.get(section):raise ValueError('Статистика отчёта ещё не собрана')
    source=source if source is not None else (Path(base)/{'dashboard':'hh-dashboard.html','activity':'hh-activity.html'}[name]).read_text()
    value={**data[section],'statistics_revision':data['revision']}
    encoded=json.dumps(value,ensure_ascii=False).replace('<','\\u003c')
    element='data' if name=='dashboard' else 'd'
    source=re.sub(r'(<script id="'+element+r'" type="application/json">).*?(</script>)',lambda m:m[1]+encoded+m[2],source,flags=re.S)
    if export:source='<script>window.__REPORT_EXPORT__=true</script>'+source
    return source


def recent_application_runs(base):
    """Two latest real application runs, read directly from atomic run ledgers."""
    result=[]
    for path in sorted((Path(base)/'.state/runs').glob('hh-*.json'),reverse=True):
        try:
            run=json.loads(path.read_text())
            if not isinstance(run,dict) or run.get('action')!='apply' or run.get('mode')!='live':continue
            rows=run.get('results',[])
            if not isinstance(rows,list):continue
            sent={str(row['vacancy_id']) for row in rows if isinstance(row,dict) and row.get('status')=='sent' and row.get('vacancy_id') is not None}
            result.append({'sent':len(sent),'started_at':run.get('started_at'),'finished_at':run.get('finished_at')})
        except (OSError,ValueError,TypeError):continue
        if len(result)==2:break
    return result
