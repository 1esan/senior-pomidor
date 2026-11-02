from python_runtime import python_command
"""Personal macOS launcher. Starts services only; never starts sending jobs."""
from pathlib import Path
import argparse, fcntl, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error

BASE = Path(__file__).resolve().parent
PANEL = 'http://127.0.0.1:8768'
ADAPTER = 'http://127.0.0.1:8766'

class LaunchError(RuntimeError): pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward local service keys to a redirect destination."""
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None

def configuration():
    try:config=json.loads((BASE/'personal_launcher.json').read_text())
    except FileNotFoundError:config={}
    if not isinstance(config,dict):raise LaunchError('Настройки запуска должны быть JSON-объектом.')
    timeout=float(config.get('startup_timeout_seconds',35))
    if not 1 <= timeout <= 120: raise LaunchError('Некорректное время запуска в настройках.')
    config['timeout']=timeout
    return config

def configured_services(config):
    """The panel is usable without an adapter; an adapter is explicitly opt-in."""
    services=[('panel',PANEL,BASE/'.state/console-key','X-Console-Key',('profile','operations'),python_command('-u',str(BASE/'setup_console.py'),'--no-open'),BASE)]
    raw=os.environ.get('SENIOR_POMIDOR_ADAPTER_DIR') or config.get('adapter_dir')
    if raw:
        adapter=Path(raw).expanduser()
        if not adapter.is_absolute():raise LaunchError('Путь к адаптеру должен быть абсолютным.')
        node=config.get('node') or shutil.which('node') or ''
        services.insert(0,('gpt',ADAPTER,adapter/'.state/adapter-key','X-Adapter-Token',('status','sharing'),[node,str(adapter/'server.mjs'),'--no-browser'],adapter))
    return services

def probe(url, key_file, header, expected):
    """Only trust an authenticated response of the expected local service."""
    try: key=Path(key_file).read_text().strip()
    except FileNotFoundError: key=''
    request=urllib.request.Request(url+'/api/status',headers={header:key})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    try:
        with opener.open(request,timeout=2) as response:
            data=json.loads(response.read(2_000_000))
        return 'ready' if isinstance(data,dict) and all(k in data for k in expected) else 'occupied'
    except urllib.error.HTTPError: return 'occupied'
    except (urllib.error.URLError,TimeoutError,ConnectionError): return 'down'
    except (ValueError,OSError): return 'occupied'

def ensure_service(name, url, key_file, header, expected, command, cwd, timeout):
    state=probe(url,key_file,header,expected)
    if state=='ready': return 'already_running'
    if state=='occupied': raise LaunchError(f'{name}: адрес занят другим сервисом или не подходит ключ подключения. Ничего не перезапущено.')
    if not Path(command[0]).is_file() or not os.access(command[0],os.X_OK):
        raise LaunchError(f'{name}: не найден исполняемый файл. Проверь настройки запуска.')
    if not Path(cwd).is_dir(): raise LaunchError(f'{name}: не найдена рабочая папка.')
    log_path=BASE/'logs'/('launcher-'+name+'.log')
    fd=os.open(log_path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
    with os.fdopen(fd,'a') as output:
        child=subprocess.Popen(command,cwd=cwd,stdin=subprocess.DEVNULL,stdout=output,stderr=output,start_new_session=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        state=probe(url,key_file,header,expected)
        if state=='ready': return 'started'
        if child.poll() is not None:
            # Another launcher may have won the bind race; accept only our authenticated service.
            if probe(url,key_file,header,expected)=='ready': return 'already_running'
            raise LaunchError(f'{name}: служба завершилась при запуске. Журнал: {log_path}')
        time.sleep(.4)
    raise LaunchError(f'{name}: запуск ещё не подтвердился. Повтори открытие через минуту. Журнал: {log_path}')

def notify(message):
    script='on run argv\n display dialog (item 1 of argv) with title "Сеньор Помидор" buttons {"Понятно"} default button 1\nend run'
    subprocess.run(['/usr/bin/osascript','-e',script,message],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--no-open',action='store_true')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args(argv)
    config=configuration()
    services=configured_services(config)
    if args.check:
        print(json.dumps({name:probe(url,key,header,expected) for name,url,key,header,expected,*_ in services},ensure_ascii=False))
        return 0
    (BASE/'logs').mkdir(exist_ok=True)
    lock=BASE/'.state/personal-launcher.lock'
    lock.parent.mkdir(exist_ok=True,mode=0o700)
    warnings=[]; result={}
    with lock.open('a') as handle:
        os.chmod(lock,0o600)
        fcntl.flock(handle,fcntl.LOCK_EX)
        for name,url,key,header,expected,command,cwd in services:
            try: result[name]=ensure_service(name,url,key,header,expected,command,cwd,config['timeout'])
            except LaunchError as error:
                warnings.append(str(error));result[name]='unavailable'
        with (BASE/'logs/hh-status-monitor.log').open('a') as monitor_log:
            subprocess.Popen(python_command('-u',str(BASE/'hh_status_monitor.py')),cwd=BASE,stdin=subprocess.DEVNULL,stdout=monitor_log,stderr=monitor_log,start_new_session=True)
        snapshot={'at':time.time(),'services':result,'warnings':warnings}
        target=BASE/'.state/personal-launcher.json'
        temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2));temporary.chmod(0o600);temporary.replace(target)
    if not args.no_open and result.get('panel')!='unavailable': subprocess.run(['/usr/bin/open',PANEL],check=True)
    if warnings:
        if not args.no_open: notify('\n\n'.join(warnings))
        print('\n'.join(warnings),file=sys.stderr)
        return 1
    print('Панель готова. Отправки запускаются только из панели.')
    if not any(item[0]=='gpt' for item in services):print('ИИ-адаптер не настроен. Его можно подключить отдельно.')
    return 0

if __name__=='__main__':
    try: sys.exit(main())
    except Exception:
        # Never display response bodies or credentials in desktop notifications.
        if '--no-open' not in sys.argv and '--check' not in sys.argv: notify('Не удалось открыть бота. Проверь наличие папки и настройки personal_launcher.json.')
        raise
