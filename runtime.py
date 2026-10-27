"""Shared process locks and private atomic state on Mac."""
import fcntl,json,os,signal,time
from contextlib import contextmanager
from common import BASE

def save_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2));tmp.chmod(0o600);tmp.replace(path)

@contextmanager
def operation_lock(name):
    folder=BASE/'.state/locks';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (folder/(name+'.lock')).open('a') as f:
        os.chmod(f.name,0o600)
        try: fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('Этот канал уже занят другим запуском')
        try: yield
        finally: fcntl.flock(f,fcntl.LOCK_UN)

def repeat_pass(fn,minutes=0,interval=300,clock=time.monotonic,sleep=time.sleep):
    if minutes<0 or minutes>1440 or interval<30 or interval>86400: raise ValueError('Некорректный интервал/длительность')
    end=clock()+minutes*60;count=0
    while True:
        result=fn();count+=1
        if result not in (None,0): return result
        if not minutes or clock()+interval>=end: return 0
        sleep(interval)
