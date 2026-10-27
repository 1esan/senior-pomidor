from python_runtime import python_command
"""Single local report watcher. Does not start bots or access HH/Telegram."""
import fcntl
import logging
import subprocess
import sys
import time
from pathlib import Path
from common import BASE,HH_CONFIG

def signature():
    paths=[BASE/'.state/hh-negotiation-statuses.json',BASE/'.state/hh-status-monitor.json',BASE/'application_status.py',BASE/'logs/giga-bot.log',BASE/'.state/giga-autonomous.json',BASE/'.state/giga-catalog.json',BASE/'hh-data.json',BASE/'hh-activity.py',BASE/'conversation_statistics.py',HH_CONFIG/'log.txt',HH_CONFIG/'log.txt.1']
    for folder,pattern in [('.state/telegram-progress','*-live.json'),('.state/jobs','*.json'),('.state/runs','hh-*.json'),('.state/batches','*/dispatch.json')]:paths.extend((BASE/folder).glob(pattern))
    result=[]
    for path in sorted(paths):
        try:s=path.stat();result.append((str(path),s.st_mtime_ns,s.st_size))
        except FileNotFoundError:pass
    return result

def main():
    folder=BASE/'.state/services';folder.mkdir(parents=True,exist_ok=True)
    with (folder/'activity-monitor.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        old=None;last=0
        while True:
            try:
                current=signature()
                if current!=old or time.monotonic()-last>=60:
                    result=subprocess.run(python_command('-u',str(BASE/'hh-activity.py')),cwd=BASE,timeout=45)
                    if result.returncode==0:old=current;last=time.monotonic()
            except Exception:logging.exception('Activity refresh failed; previous report retained')
            time.sleep(5)

if __name__=='__main__':main()
