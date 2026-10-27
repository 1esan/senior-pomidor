from python_runtime import python_command
from pathlib import Path
import json, secrets, subprocess, sys, threading, webbrowser, time
from flask import Flask, request, jsonify, Response, send_file, redirect
from common import BASE, auth_status, write_status

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH']=10*1024*1024
import operations
from statistics_store import read_statistics,render_report,recent_application_runs
from profile_editor import extract_text,save_profile,FIELDS
from bot_cli import prepare_schedule
key_path = BASE / '.state/console-key'
if not key_path.exists():
    key_path.write_text(secrets.token_urlsafe(32)); key_path.chmod(0o600)
key = key_path.read_text().strip()
jobs = {}
report_job = None
job_lock = threading.Lock()
REPORTS = {'dashboard':'hh-dashboard.html', 'activity':'hh-activity.html', 'pdf':'Разбор откликов hh.ru.pdf'}
PIPELINES = {'dashboard':[['hh-dash.py'],['hh-activity.py']], 'full':[['hh-analyze.py'],['hh-agg.py'],['hh-dash.py','--from-analysis'],['hh-activity.py'],['hh-dash-pdf.py']],
             'analysis':[['hh-analyze.py'],['hh-agg.py'],['hh-dash.py','--from-analysis'],['hh-activity.py'],['hh-dash-pdf.py']], 'activity':[['hh-activity.py']],
             'pdf':[['hh-dash-pdf.py']]}

@app.before_request
def guard():
    if request.host != '127.0.0.1:8768': return jsonify(error='host_not_allowed'),403
    if request.headers.get('Origin') not in (None,'http://127.0.0.1:8768'): return jsonify(error='origin_not_allowed'),403
    if request.path.startswith('/api/') and not secrets.compare_digest(request.headers.get('X-Console-Key',''),key):
        return jsonify(error='auth_required'),401
    if request.path.startswith('/reports/') and not secrets.compare_digest(request.cookies.get('console',''),key):
        return jsonify(error='open_console_first'),401

@app.after_request
def headers(response):
    response.headers['Cache-Control']='no-store'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    return response

def connect(channel):
    if channel in jobs and jobs[channel].poll() is None:return
    write_status(channel,{'status':'opening_browser'})
    with (BASE/'logs'/f'auth-{channel}.log').open('a') as log:
        jobs[channel]=subprocess.Popen(python_command(str(BASE/'auth_accounts.py'),channel),cwd=BASE,stdout=log,stderr=log)

def reports_state():
    state={}
    for name, filename in REPORTS.items():
        path=BASE/filename
        state[name]={'exists':path.is_file(),'updated_at':path.stat().st_mtime if path.is_file() else None,'url':'/reports/'+name}
    statistics=read_statistics(BASE)
    dashboard=statistics.get('dashboard')
    state['summary']={'generated_at':dashboard['gen'],'mode':dashboard['mode'],'funnel':dashboard['funnel'],'heavy_generated_at':(dashboard.get('heavy') or {}).get('gen')} if dashboard else None
    activity=statistics.get('activity')
    state['activity']['source']={'generated_at':activity['gen']} if activity else None
    state['pdf']['source']=statistics.get('pdf')
    state['statistics_revision']=statistics['revision']
    with job_lock:state['job']=dict(report_job) if report_job else None
    return state

def run_report(name):
    global report_job
    log_path=BASE/'logs'/f'report-{name}.log'
    try:
        from runtime import operation_lock
        with operation_lock('hh'), log_path.open('w') as log:
            log_path.chmod(0o600)
            for command in PIPELINES[name]:
                completed=subprocess.run(python_command('-u',*command),cwd=BASE,stdout=log,stderr=log)
                if completed.returncode:
                    output=log_path.read_text(errors='replace')
                    message='Нужна ручная проверка hh.ru' if 'CaptchaRequired' in output or 'captcha_required' in output else 'Обновление не завершено; смотри журнал отчёта'
                    with job_lock:report_job.update(status='failed',message=message,finished_at=time.time())
                    return
        with job_lock:report_job.update(status='completed',message='Отчёт обновлён',finished_at=time.time())
    except Exception:
        with job_lock:report_job.update(status='failed',message='Не удалось запустить обновление',finished_at=time.time())

@app.get('/')
def index():
    response=Response((BASE/'setup.html').read_text().replace('__KEY__',json.dumps(key)),mimetype='text/html')
    response.set_cookie('console',key,httponly=True,samesite='Strict')
    return response

@app.get('/api/status')
def status():
    p=json.loads((BASE/'giga_profile.json').read_text())
    try:prepared=json.loads((BASE/'preparation-status.json').read_text())
    except (FileNotFoundError,ValueError):prepared={}
    latest_run=read_statistics(BASE).get('latest_run')
    from hh_captcha import read_state
    challenge=read_state(BASE)
    public_captcha={k:v for k,v in challenge.items() if k!='url'}
    return jsonify(apply_runs=recent_application_runs(BASE),captcha=public_captcha,latest_run=latest_run,hh=auth_status('hh'),telegram=auth_status('telegram'),profile={'name':p.get('name'),'city':p.get('city'),'salary_min':p.get('salary_min'),'salary_max':p.get('salary_max'),'confirmed':p.get('profile_confirmed')},reports=reports_state(),last_batch=prepared.get('last_batch'),operations=operations.state(),scope='Все операции доступны; отправка требует режима Отправка и подтверждения.')

@app.post('/api/connect/<channel>')
def start(channel):
    if channel not in ('hh','telegram'):return jsonify(error='unknown_channel'),400
    if operations.active():return jsonify(error='Сначала остановите текущую операцию'),409
    connect(channel);return jsonify(started=True)

@app.post('/api/reports/<name>/refresh')
def refresh_report(name):
    global report_job
    if name not in PIPELINES:return jsonify(error='unknown_report'),400
    if operations.active():return jsonify(error='operation_already_running'),409
    if name=='pdf' and not (BASE/REPORTS['dashboard']).is_file():return jsonify(error='build_dashboard_first'),409
    with job_lock:
        if report_job and report_job['status']=='running':return jsonify(error='report_already_running'),409
        report_job={'name':name,'status':'running','started_at':time.time(),'message':'Обновляю отчёт…'}
    threading.Thread(target=run_report,args=(name,),daemon=True).start()
    return jsonify(started=True),202

@app.get('/reports/hh-captcha')
def open_hh_captcha():
    from hh_captcha import read_state,valid_url
    current=read_state(BASE)
    if current.get('status') not in ('waiting','resume_requested','checking') or not valid_url(current.get('url')):
        return jsonify(error='Активной проверки нет. Запусти отклики и дождись запроса капчи.'),409
    return redirect(current['url'],code=302)

@app.post('/api/hh/captcha/resume')
def resume_hh_captcha():
    from hh_captcha import read_state
    from runtime import save_json
    current=read_state(BASE)
    if current.get('status')!='waiting' or not any(j.get('id')==current.get('job_id') and j.get('status')=='running' for j in operations.state()):
        return jsonify(error='Нет запуска, ожидающего капчу'),409
    save_json(BASE/'.state/hh-captcha.json',{**current,'status':'resume_requested'})
    return jsonify(resuming=True)

@app.get('/reports/statistics')
def statistics_read():
    return jsonify(read_statistics(BASE))

@app.get('/reports/meta')
def report_metadata():
    return jsonify(reports_state())

@app.get('/reports/<name>')
def report(name):
    if name not in REPORTS:return jsonify(error='unknown_report'),404
    path=BASE/REPORTS[name]
    if not path.is_file():return jsonify(error='report_not_built'),404
    if name=='pdf':return send_file(path,mimetype='application/pdf')
    try:return Response(render_report(BASE,name),mimetype='text/html')
    except ValueError as e:return jsonify(error=str(e)),409


@app.get('/api/profile')
def profile_read():
    p=json.loads((BASE/'giga_profile.json').read_text())
    return jsonify(profile={k:p.get(k) for k in FIELDS},excluded_employers=[{'company':e['company'],'ids':e.get('hh_ids',[])} for e in p.get('excluded_employers',[])])

@app.post('/api/profile')
def profile_save():
    if operations.active():return jsonify(error='Сначала остановите выполняющийся запуск'),409
    try:save_profile(request.get_json());return jsonify(saved=True)
    except (ValueError,TypeError,RuntimeError) as e:return jsonify(error=str(e)),400

@app.post('/api/resume/extract')
def resume_extract():
    f=request.files.get('resume')
    if not f:return jsonify(error='Выберите файл'),400
    try:return jsonify(text=extract_text(f.filename,f.read()))
    except Exception:return jsonify(error='Не удалось прочитать файл. Используйте PDF с текстом, DOCX, TXT или MD'),400

@app.post('/api/operations/<action>/start')
def operation_start(action):
    with job_lock:
        if report_job and report_job['status']=='running':return jsonify(error='Дождитесь завершения отчёта'),409
        if any(p.poll() is None for p in jobs.values()):return jsonify(error='Дождитесь завершения входа в аккаунт'),409
        try:return jsonify(job=operations.start(action,request.get_json() or {})),202
        except (ValueError,RuntimeError) as e:return jsonify(error=str(e)),400

@app.post('/api/operations/<job_id>/stop')
def operation_stop(job_id):
    try:return jsonify(job=operations.stop(job_id))
    except ValueError as e:return jsonify(error=str(e)),400

@app.get('/api/operations/<job_id>/log')
def operation_log(job_id):
    try:return jsonify(text=operations.log_tail(job_id))
    except ValueError as e:return jsonify(error=str(e)),404

@app.post('/api/schedule/prepare')
def schedule_prepare():
    prepare_schedule();return jsonify(prepared=True,enabled=False,times=['09:00','13:00','17:00','21:00'],mode='preview')

@app.get('/api/telethon')
def telethon_status():
    return jsonify(configured=(BASE/'.state/telethon-config.json').is_file(),session=(BASE/'.state/telethon.session').is_file())

@app.post('/api/telethon')
def telethon_config():
    import re
    from runtime import save_json
    if operations.active():return jsonify(error='Сначала остановите запуск'),409
    data=request.get_json() or {}
    try:
        api_id=int(data.get('api_id',0));api_hash=data.get('api_hash','').strip()
        if api_id<=0 or not re.fullmatch('[0-9a-fA-F]{32}',api_hash):raise ValueError('Нужны API ID и API Hash из my.telegram.org')
        save_json(BASE/'.state/telethon-config.json',{'api_id':api_id,'api_hash':api_hash})
        return jsonify(saved=True)
    except (TypeError,ValueError) as e:return jsonify(error=str(e)),400



@app.post('/api/telegram/bind')
def telegram_bind():
    from telegram_state import bind
    from employer_guard import ContactBlocked
    if operations.active():return jsonify(error='Сначала остановите запуск'),409
    d=request.get_json() or {}
    try:return jsonify(target=bind(d.get('label'),d.get('vacancy_id'),d.get('confirmed')))
    except (ValueError,ContactBlocked) as e:return jsonify(error=str(e)),400
    except Exception:return jsonify(error='Не удалось проверить вакансию через hh.ru'),400

def refresh_after_operations():
    global report_job
    observed = {j['id'] for j in operations.state()}
    pending = False
    while True:
        time.sleep(3)
        for j in operations.state():
            if j['id'] not in observed and j['status'] not in ('running','stopping'):
                observed.add(j['id'])
                if j['channel']=='hh': pending=True
        if not pending or operations.active(): continue
        with job_lock:
            if report_job and report_job['status']=='running': continue
            report_job={'name':'dashboard','status':'running','started_at':time.time(),'message':'Обновляю статистику после запуска…'}
        pending=False
        run_report('dashboard')

if __name__=='__main__':
    with (BASE/'logs/hh-status-monitor.log').open('a') as status_log:
        subprocess.Popen(python_command('-u',str(BASE/'hh_status_monitor.py')),cwd=BASE,stdin=subprocess.DEVNULL,stdout=status_log,stderr=status_log,start_new_session=True)
    with (BASE/'logs/activity-monitor.log').open('a') as monitor_log:
        subprocess.Popen(python_command('-u',str(BASE/'activity_monitor.py')),cwd=BASE,stdin=subprocess.DEVNULL,stdout=monitor_log,stderr=monitor_log,start_new_session=True)
    threading.Thread(target=refresh_after_operations,daemon=True).start()

    import logging
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    if '--no-open' not in sys.argv:threading.Timer(1,lambda:webbrowser.open('http://127.0.0.1:8768')).start()
    if '--telegram' in sys.argv:threading.Timer(2,lambda:connect('telegram')).start()
    print('BOT_CONSOLE_READY http://127.0.0.1:8768',flush=True)
    app.run(host='127.0.0.1',port=8768,debug=False,use_reloader=False)
