"""Read-only HH status observer. Uses the HH lock and never starts send jobs."""
import fcntl,os,time,sys
from datetime import datetime,timezone
from common import BASE,HH_CONFIG
from runtime import operation_lock,save_json
from application_status import publish_snapshot

INTERVAL=300

def refresh():
    if not (HH_CONFIG/'auth.json').exists():return {'status':'login_required','message':'Нужен вход в HH'}
    with operation_lock('hh'):
        # Build a new client each pass: respect tokens refreshed by foreground jobs.
        import common
        common._hh_reader=None
        items=[];observation_started=time.time();deadline=time.monotonic()+180
        for group in ('active','archived'):
            page=0
            while True:
                if time.monotonic()>deadline:raise RuntimeError('Status refresh timeout')
                data=common.hh_read_json(f'/negotiations?status={group}&page={page}&per_page=100')
                pages=data.get('pages',1)
                if not isinstance(pages,int) or pages>100:raise RuntimeError('Incomplete status response')
                items.extend(data.get('items',[]))
                if page+1>=pages:break
                page+=1
        at=datetime.now(timezone.utc).isoformat();snapshot=publish_snapshot(BASE,items,at,observed_since=observation_started)
        return {'status':'ready','message':'Статусы HH обновлены','last_success_at':snapshot['generated_at'],'applications':len(snapshot['rows'])}

def main():
    folder=BASE/'.state/services';folder.mkdir(exist_ok=True,parents=True,mode=0o700)
    with (folder/'hh-status-monitor.lock').open('a') as lock:
        os.chmod(lock.name,0o600)
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        while True:
            try:result=refresh()
            except RuntimeError:result={'status':'deferred','message':'Обновление отложено: HH занят или недоступен'}
            except Exception:result={'status':'attention','message':'Не удалось обновить HH: проверь вход или капчу в панели'}
            save_json(BASE/'.state/hh-status-monitor.json',{**result,'checked_at':time.time(),'pid':os.getpid(),'interval_seconds':INTERVAL})
            if '--once' in sys.argv:return
            time.sleep(INTERVAL)

if __name__=='__main__':main()
