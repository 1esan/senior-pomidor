from python_runtime import python_command
import argparse,json,subprocess,sys,webbrowser,plistlib
from common import BASE
from runtime import operation_lock,repeat_pass

def prepare_schedule():
    # Export only: no registration, no enabled tasks, no live sending by default.
    folder=BASE/'schedule';folder.mkdir(exist_ok=True)
    target=folder/'ru.seniorpomidor.hh-replies.plist'
    data={'Label':'ru.seniorpomidor.hh-replies','Disabled':True,'ProgramArguments':[str(BASE/'.venv/bin/python'),str(BASE/'hh.py'),'reply','--period','7'],
          'StartCalendarInterval':[{'Hour':h,'Minute':0} for h in (9,13,17,21)],'WorkingDirectory':str(BASE),
          'StandardOutPath':str(BASE/'logs/scheduled-reply.log'),'StandardErrorPath':str(BASE/'logs/scheduled-reply.log')}
    target.write_bytes(plistlib.dumps(data));target.chmod(0o600)
    return target

def menu():
    choices={'1':['hh.py','apply','--preset','moscow','--all-queries'],'2':['hh.py','apply','--preset','ru-cis','--all-queries'],
             '3':['hh.py','apply','--preset','abroad','--all-queries'],'4':['hh.py','reply','--period','7'],
             '5':['hh.py','reply','--period','7','--loop-minutes','60','--every-sec','300'],'6':['hh-dash.py'],
             '7':['hh-dash.py','--full'],'8':['hh-activity.py']}
    while True:
        print('\n1 Москва · 2 РФ/СНГ удалёнка · 3 Зарубежная удалёнка · 4 Ответы один раз · 5 Ответы час · 6 Дашборд · 7 С перепиской · 8 Активность · 9 Панель · 0 Выход')
        n=input('Выбор: ').strip()
        if n=='0':return 0
        if n=='9':webbrowser.open('http://127.0.0.1:8768/');continue
        if n not in choices:continue
        cmd=list(choices[n])
        if n in ('1','2','3','4','5'):
            if input('Предпросмотр по умолчанию. Для отправки напиши ОТПРАВИТЬ: ').strip()=='ОТПРАВИТЬ':cmd+=['--live']
        subprocess.run(python_command(*cmd),cwd=BASE)
        if n in ('6','7'):webbrowser.open((BASE/'hh-dashboard.html').as_uri())
        if n=='8':webbrowser.open((BASE/'hh-activity.html').as_uri())

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['menu','watch','prepare-schedule']);p.add_argument('--minutes',type=int,default=60);p.add_argument('--interval',type=int,default=300);a=p.parse_args()
    if a.action=='menu':return menu()
    if a.action=='prepare-schedule':print(prepare_schedule());return 0
    if a.interval<300:raise ValueError('Обновление не чаще пяти минут')
    with operation_lock('hh'):
        return repeat_pass(lambda:subprocess.run(python_command('hh-dash.py'),cwd=BASE).returncode,a.minutes,a.interval)
if __name__=='__main__':sys.exit(main())
