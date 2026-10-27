"""Telethon transport; same interview engine, profile and exclusions as Web."""
import time
import argparse,asyncio,getpass,importlib.util,json,os,sys
from common import BASE
from runtime import operation_lock,save_json
from telegram_state import fingerprint,load_state,begin_action,finish_action
from autonomous_runtime import NeedsDecision,status as run_status
from employer_guard import ContactBlocked

def engine():
    spec=importlib.util.spec_from_file_location('giga_engine',BASE/'giga-bot.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class TelethonTransport:
    def __init__(self,client,entity,engine):self.client=client;self.entity=entity;self.engine=engine;self.last=None
    async def scrape(self,_):
        messages=await self.client.get_messages(self.entity,limit=20)
        out=[]
        for m in reversed(messages):
            import re
            text=m.raw_text or '';section_links={};links=[]
            encoded=text.encode('utf-16-le')
            for entity in m.entities or []:
                url=getattr(entity,'url',None)
                fragment=encoded[entity.offset*2:(entity.offset+entity.length)*2].decode('utf-16-le')
                if not url and fragment.startswith('https://'):url=fragment
                if url:
                    prefix=encoded[:entity.offset*2].decode('utf-16-le')
                    numbers=list(re.finditer(r'(?:^|\s)(\d+)[.)]\s',prefix))
                    if numbers:section_links.setdefault(numbers[-1][1],[]).append(url)
                    links.append(url)
            out.append({'peer_id':str(self.entity.id),'mid':str(m.id),'dir':'out' if m.out else 'in','text':text,'buttons':[b.text for row in (m.buttons or []) for b in row],'links':links,'section_links':section_links})
        self.last=messages[0] if messages else None
        return out
    async def send(self,_,text,dry):
        e=self.engine;e.check_deadline(e.WEB_DEADLINE);e.ensure_telegram_contact()
        if str(self.entity.id)!=e.TARGET_PEER:raise RuntimeError('Неверный Telegram ID')
        if dry:e.log.info('TELEGRAM_PREVIEW: %s',text);return
        k=e.CURRENT_MESSAGE+':text:'+__import__('hashlib').sha256(text.encode()).hexdigest()
        begin_action(e.STATE_PATH,e.PROGRESS,k)
        sent=await self.client.send_message(self.entity,text,parse_mode=None)
        if not sent or not sent.id:raise RuntimeError('Отправка не подтверждена')
        finish_action(e.STATE_PATH,e.PROGRESS,k);e.log.info('TELEGRAM_SUBMITTED: peer_id=%s Telethon message ID %s',self.entity.id,sent.id)
    async def click(self,_,label,dry):
        e=self.engine;e.check_deadline(e.WEB_DEADLINE)
        if e.clean_label(label)!='далее':e.ensure_telegram_contact(label)
        if str(self.entity.id)!=e.TARGET_PEER:raise RuntimeError('Неверный Telegram ID')
        if dry:e.log.info('TELEGRAM_PREVIEW кнопка: %s',label);return True
        # Never activate URL/auth/phone/location request buttons.
        from telethon.tl.types import KeyboardButtonCallback,KeyboardButton
        await self.scrape(None)
        if not self.last or fingerprint((await self.scrape(None))[-1])!=e.CURRENT_MESSAGE:raise NeedsDecision('Вопрос изменился; нажатие остановлено')
        for row in (self.last.buttons or []) if self.last else []:
            for b in row:
                if b.text==label:
                    if not isinstance(b.button,(KeyboardButtonCallback,KeyboardButton)):raise RuntimeError('Эта кнопка требует ручного решения')
                    k=e.CURRENT_MESSAGE+':button:'+label;begin_action(e.STATE_PATH,e.PROGRESS,k)
                    previous_mid=str(self.last.id)
                    await b.click()
                    new=await e.wait_for_new_message(None,previous_mid,120,step=1,previous_fp=e.CURRENT_MESSAGE,require_non_menu=e.is_menu(self.last.raw_text or '',[label]) and e.clean_label(label)!='далее')
                    if not new:raise NeedsDecision('Telethon не подтвердил результат нажатия; повтор отключён')
                    finish_action(e.STATE_PATH,e.PROGRESS,k);return True
        return False

async def main(args):
    from telethon import TelegramClient
    cfg_path=BASE/'.state/telethon-config.json'
    if not cfg_path.is_file():raise RuntimeError('Добавь API ID/API Hash в панели, затем выполни Подключить_Telethon.command')
    cfg=json.loads(cfg_path.read_text());session=BASE/'.state/telethon'
    proxy=cfg.get('proxy')
    client=TelegramClient(str(session),cfg['api_id'],cfg['api_hash'],proxy=proxy,request_retries=0,connection_retries=2,flood_sleep_threshold=0)
    await client.connect()
    try:
        if args.login:
            if not sys.stdin.isatty():raise RuntimeError('Вход выполняется из терминала')
            phone=input('Телефон Telegram: ').strip()
            if not await client.is_user_authorized():
                await client.send_code_request(phone)
                from telethon.errors import SessionPasswordNeededError
                try:await client.sign_in(phone,getpass.getpass('Код из Telegram: '))
                except SessionPasswordNeededError:await client.sign_in(password=getpass.getpass('Пароль двухэтапной проверки: '))
            print('Вход Telethon сохранён');return
        if not await client.is_user_authorized():raise RuntimeError('Сначала выполни Подключить_Telethon.command')
        e=engine();e.VACANCY_STRATEGY=args.strategy;e.AUTO_NEXT=not args.no_auto_next
        dry=not args.live
        if not args.inspect and not await e.ollama_alive():raise RuntimeError('Генератор недоступен')
        entity=await client.get_entity(e.BOT)
        if str(entity.id)!=e.TARGET_PEER or not getattr(entity,'bot',False) or (entity.username or '').lower()!=e.BOT.lower():raise RuntimeError('Адресат не подтверждён')
        e.WEB_DEADLINE=time.time()+args.minutes*60
        t=TelethonTransport(client,entity,e);e.scrape=t.scrape;e.type_and_send=t.send;e.click_button=t.click
        e.STATE_PATH,e.PROGRESS=load_state('telethon',dry)
        e.migrate_context(e.PROGRESS,e.STATE_PATH)
        handled=set(e.PROGRESS.get('handled',[]));e.DONE_VACANCIES.update(e.PROGRESS.get('done',[]));e.CUR_VACANCY.update(e.PROGRESS.get('current',{}))
        e._history.clear()
        first=True;last_activity=time.time()
        run_status('running',phase='waiting_recruiter',message='Telethon подключён; проверяю текущий диалог')
        end=e.WEB_DEADLINE
        while time.time()<end:
            bubbles=await t.scrape(None)
            if bubbles:
                last=bubbles[-1];fp=fingerprint(last)
                intros=[b for b in bubbles if b['dir']=='in' and e.intro_identity(b.get('text',''))]
                if not args.inspect and not e.is_menu(last['text'],last['buttons']) and intros and fingerprint(intros[-1])!=e.CUR_VACANCY.get('intro_fingerprint'):
                    await e.establish_interview(intros[-1])
                notices=e.terminal_notices(bubbles,handled,e.CUR_VACANCY)
                if not args.inspect and notices:
                    e.finish_current_interview();e.PROGRESS['awaiting_menu']=True
                    handled.update(fingerprint(n) for n in notices)
                if args.inspect:e.log.info('Чтение: %s',last)
                elif last['dir']=='in' and e.should_handle_message(fp,handled,first=first,menu=e.is_menu(last['text'],last['buttons']),auto_next=e.AUTO_NEXT,autonomous=False):
                    e.CURRENT_MESSAGE=fp
                    await e.handle_last(None,last,dry)
                    last_activity=time.time()
                    handled.add(fp);e.PROGRESS.update(handled=list(handled),done=list(e.DONE_VACANCIES),current=e.CUR_VACANCY);save_json(e.STATE_PATH,e.PROGRESS)
            first=False
            if args.once or e.INTERVIEW_COMPLETED:break
            if time.time()-last_activity>e.CONFIG['recruiter_wait_seconds']:raise NeedsDecision('ГигаРекрутёр не отвечает; прогресс сохранён')
            await asyncio.sleep(e.POLL_SEC)
        if not e.INTERVIEW_COMPLETED:run_status('expired',phase='expired',message='Время запуска истекло; прогресс сохранён')
    finally:
        await client.disconnect()
        for f in BASE.glob('.state/telethon.session*'):f.chmod(0o600)

def parser():
    p=argparse.ArgumentParser(description='Telethon: по умолчанию предпросмотр')
    p.add_argument('--login',action='store_true');p.add_argument('--live',action='store_true');p.add_argument('--dry-run',action='store_true');p.add_argument('--inspect',action='store_true');p.add_argument('--minutes',type=int,default=60);p.add_argument('--strategy',choices=['first','senior'],default='first');p.add_argument('--no-auto-next',action='store_true');p.add_argument('--once',action='store_true');return p
if __name__=='__main__':
    a=parser().parse_args()
    if not 1<=a.minutes<=1440 or a.live and (a.dry_run or a.inspect):raise SystemExit('Некорректный режим или длительность')
    try:
        with operation_lock('telegram'):asyncio.run(main(a))
    except KeyboardInterrupt:run_status('stopped',phase='stopped',message='Запуск остановлен пользователем')
    except (NeedsDecision,ContactBlocked) as ex:
        run_status('needs_attention',phase='needs_attention',message=str(ex));print(str(ex),file=sys.stderr);sys.exit(20)
    except Exception as ex:print(str(ex),file=sys.stderr);sys.exit(1)
