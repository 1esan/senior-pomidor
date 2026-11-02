import sys,os,asyncio,time,unittest,logging,importlib.util
from unittest.mock import patch,AsyncMock
from pathlib import Path
B=Path(__file__).resolve().parents[1];sys.path.insert(0,str(B));os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(B/'.browsers')
from playwright.async_api import async_playwright
import telegram_web_guard as g
with patch('logging.FileHandler',return_value=logging.NullHandler()):
 spec=importlib.util.spec_from_file_location('native_test_engine',B/'giga-bot.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
HTML=f'<div class="chat"><div class="bubbles"><div class="bubble is-in" data-mid="210"><div class="message">Вопрос</div><button class="reply-markup-button">Выбрать</button></div></div><div class="input-message-input" contenteditable="true" data-peer-id="{m.TARGET_PEER}"></div></div>'
class NativeTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.status_patch=patch.object(m,'run_status');self.status_patch.start();self.addCleanup(self.status_patch.stop)
  self.p=await async_playwright().start();self.b=await self.p.chromium.launch(headless=True,channel='chromium');self.c=await self.b.new_context();await self.c.set_offline(True);self.page=await self.c.new_page();await self.page.set_content(HTML);await g.bind_page(self.page,time.time()+60)
 async def asyncTearDown(self):await self.b.close();await self.p.stop()
 async def prepare_recovery_send(self):
  await self.page.evaluate("""() => {document.querySelector('.bubble').className='bubble is-out';document.querySelector('.message').textContent='Мой ответ';document.querySelector('.input-message-input').textContent='/change_vacancy';const b=document.createElement('button');b.className='btn-send send';window.sends=0;b.onclick=()=>window.sends++;document.querySelector('.chat').append(b);}""")
  return {'mid':'210','source_text':'Мой ответ','source_direction':'out','recovery':True,'text':'/change_vacancy'}
 async def test_recovery_command_can_follow_exact_outgoing_message(self):
  arg=await self.prepare_recovery_send();await g.dispatch(self.page,g.SEND_JS,arg)
  self.assertEqual(await self.page.evaluate('sends'),1)
 async def test_recovery_command_rejects_late_incoming_question(self):
  arg=await self.prepare_recovery_send()
  await self.page.evaluate("""() => {const b=document.createElement('div');b.className='bubble is-in';b.dataset.mid='211';b.innerHTML='<div class="message">Новый вопрос</div>';document.querySelector('.bubbles').append(b);}""")
  with self.assertRaises(g.QuestionChanged):await g.dispatch(self.page,g.SEND_JS,arg)
  self.assertEqual(await self.page.evaluate('sends'),0)
 async def test_regular_answer_cannot_follow_outgoing_even_with_recovery_flag(self):
  arg=await self.prepare_recovery_send();arg['text']='Обычный ответ'
  await self.page.evaluate("() => document.querySelector('.input-message-input').textContent='Обычный ответ'")
  with self.assertRaises(g.QuestionChanged):await g.dispatch(self.page,g.SEND_JS,arg)
  self.assertEqual(await self.page.evaluate('sends'),0)
 async def test_changed_question_before_native_arm_is_recoverable_without_click(self):
  await self.page.evaluate("""() => {window.sent=[];document.querySelector('button').onclick=()=>sent.push('clicked');const b=document.createElement('div');b.className='bubble is-in';b.dataset.mid='211';b.innerHTML='<div class="message">Следующий вопрос</div>';document.querySelector('.bubbles').append(b);}""")
  with self.assertRaises(g.QuestionChanged):await g.native_button(self.page,'Выбрать',{'mid':'210','source_text':'Вопрос'})
  self.assertEqual(await self.page.evaluate('sent'),[])
 async def test_trusted_click_is_activated_once(self):
  await self.page.evaluate("() => {window.events=[];document.querySelector('button').onclick=e=>{if(e.isTrusted)events.push('accepted');};}")
  await g.native_button(self.page,'Выбрать',{'mid':'210','source_text':'Вопрос'})
  self.assertEqual(await self.page.evaluate('events'),['accepted'])
 async def test_old_identical_menu_is_not_clicked(self):
  await self.page.evaluate("() => {window.events=[];const current=document.querySelector('.bubble');current.querySelector('button').onclick=()=>events.push('current');const old=current.cloneNode(true);old.dataset.mid='200';old.querySelector('.message').textContent='Старое меню';old.querySelector('button').onclick=()=>events.push('old');document.querySelector('.bubbles').prepend(old);}")
  await g.native_button(self.page,'Выбрать',{'mid':'210','source_text':'Вопрос'})
  self.assertEqual(await self.page.evaluate('events'),['current'])
 async def test_switch_during_press_blocks_click(self):
  await self.page.evaluate("() => {window.events=[];document.querySelector('button').onmousedown=()=>{document.querySelector('.input-message-input').dataset.peerId='123';};document.querySelector('button').onclick=()=>events.push('bad');}")
  with self.assertRaises(g.NeedsDecision):await g.native_button(self.page,'Выбрать',{'mid':'210','source_text':'Вопрос'})
  self.assertEqual(await self.page.evaluate('events'),[])
 async def test_callback_timeout_waits_full_budget_before_stopping(self):
  await g.native_button(self.page,'Выбрать',{'mid':'210','source_text':'Вопрос'})
  await self.page.evaluate("() => window.dispatchEvent(new PromiseRejectionEvent('unhandledrejection',{promise:Promise.resolve(),reason:{type:'BOT_RESPONSE_TIMEOUT'}}))")
  m.WEB_DEADLINE=time.time()+20
  started=time.monotonic()
  with self.assertRaisesRegex(m.NeedsDecision,'BOT_RESPONSE_TIMEOUT'):
   await m.wait_for_new_message(self.page,'210',5)
  self.assertGreaterEqual(time.monotonic()-started,4.8)
  self.assertLess(time.monotonic()-started,7)
 async def test_late_reply_after_callback_timeout_continues_without_second_click(self):
  await self.page.evaluate("() => {window.clickCount=0;document.querySelector('button').onclick=()=>clickCount++;}")
  await g.native_button(self.page,'Выбрать',{'mid':'210','source_text':'Вопрос'})
  await self.page.evaluate("""() => {window.__candidateBotScope.callbackError='BOT_RESPONSE_TIMEOUT';setTimeout(()=>{const bubble=document.createElement('div');bubble.className='bubble is-in';bubble.dataset.mid='211';bubble.innerHTML='<div class="message">Здравствуйте! Начало интервью</div>';document.querySelector('.bubbles').append(bubble);},3000);}""")
  m.WEB_DEADLINE=time.time()+20
  result=await m.wait_for_new_message(self.page,'210',7,require_non_menu=True)
  self.assertEqual(result['mid'],'211')
  self.assertEqual(await self.page.evaluate('clickCount'),1)
 async def test_callback_wait_is_bounded_by_run_deadline(self):
  await self.page.evaluate("() => window.__candidateBotScope.callbackError='BOT_RESPONSE_TIMEOUT'")
  m.WEB_DEADLINE=time.time()+1
  started=time.monotonic()
  with self.assertRaises(m.NeedsDecision):await m.wait_for_new_message(self.page,'210',120)
  self.assertLess(time.monotonic()-started,2.5)
 async def test_edited_reply_wins_over_callback_timeout(self):
  await self.page.evaluate("() => {window.__candidateBotScope.callbackError='BOT_RESPONSE_TIMEOUT';}")
  old={'mid':'210','peer_id':g.TARGET_PEER,'dir':'in','text':'Меню','buttons':['Кнопка']}
  edited={**old,'text':'Спасибо за выбор вакансии! Дайте мне несколько секунд — и мы начнем диалог','buttons':[]}
  m.WEB_DEADLINE=time.time()+20
  with patch.object(m,'scrape',new=AsyncMock(return_value=[edited])):
   result=await m.wait_for_new_message(self.page,'210',5,previous_fp=m.fingerprint(old),require_non_menu=True)
  self.assertEqual(result,edited)
 async def test_waiting_ack_never_calls_model(self):
  bubble={'text':'Спасибо за выбор вакансии! Дайте мне несколько секунд — и мы начнем диалог 👍','buttons':[]}
  with patch.object(m,'ollama_chat') as model:
   await m.handle_last(None,bubble,False)
  model.assert_not_called()
 async def test_same_titles_keep_links_in_their_own_numbered_sections(self):
  await self.page.evaluate("""() => {document.querySelector('.message').innerHTML='<div>1. <a href="https://rabota.sber.ru/search/111">Системный аналитик</a></div><div>Описание первой.</div><div>2. <a href="https://rabota.sber.ru/search/222">Системный аналитик</a></div>'; }""")
  m.WEB_DEADLINE=time.time()+20
  bubbles=await m.scrape(self.page)
  self.assertEqual(bubbles[-1]['section_links'],{'1':['https://rabota.sber.ru/search/111'],'2':['https://rabota.sber.ru/search/222']})
 async def test_number_inside_anchor_does_not_drop_or_shift_row_links(self):
  await self.page.evaluate("""() => {document.querySelector('.message').innerHTML='<div><a href="https://rabota.sber.ru/search/111">1. Системный аналитик</a></div><div>Описание первой.</div><div><a href="https://www.rabota.ru/vacancy/222/">2. Системный аналитик</a></div>'; }""")
  m.WEB_DEADLINE=time.time()+20
  bubbles=await m.scrape(self.page)
  self.assertEqual(bubbles[-1]['section_links'],{'1':['https://rabota.sber.ru/search/111'],'2':['https://www.rabota.ru/vacancy/222/']})
 async def test_history_waits_for_delayed_real_dom_messages(self):
  await self.page.evaluate("""() => {document.querySelector('.bubbles').innerHTML='';setTimeout(()=>{document.querySelector('.bubbles').innerHTML='<div class="bubble is-in" data-mid="220"><div class="message">Загруженное меню</div></div>';},150);}""")
  m.WEB_DEADLINE=time.time()+20
  with patch.dict(m.CONFIG,history_load_timeout_seconds=5,history_stable_seconds=.2),patch.object(m,'run_status'):
   result=await m.wait_history(self.page)
  self.assertEqual(result[-1]['text'],'Загруженное меню')
  self.assertEqual(result[-1]['mid'],'220')
 async def test_edited_message_is_detected(self):
  old={'mid':'210','peer_id':g.TARGET_PEER,'dir':'in','text':'Вопрос','buttons':[]};edited={**old,'text':'Новый вопрос'};m.WEB_DEADLINE=time.time()+20
  with patch.object(m,'scrape',new=AsyncMock(return_value=[edited])):
   result=await m.wait_for_new_message(None,'210',5,previous_fp=m.fingerprint(old))
  self.assertEqual(result,edited)
if __name__=='__main__':unittest.main()
