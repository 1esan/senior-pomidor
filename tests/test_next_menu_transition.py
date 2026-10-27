import asyncio,importlib.util,json,logging,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,AsyncMock,patch
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
with patch('logging.FileHandler',return_value=logging.NullHandler()):
 spec=importlib.util.spec_from_file_location('next_menu_engine',BASE/'giga-bot.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
import telegram_web_guard as guard

class NextMenuTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);m.STATE_PATH=Path(self.temp.name)/'progress.json';m.PROGRESS={'actions':{}};m.CUR_VACANCY.clear();m.CUR_VACANCY.update(vacancy_id='12');m.WEB_DEADLINE=1000;self.now=100.
  self.patches=[patch.object(m,'time',Mock(time=lambda:self.now)),patch.object(m,'settings',return_value={'post_interview_menu_wait_seconds':1}),patch.object(m,'run_status'),patch.object(m,'check_deadline',side_effect=lambda expires:guard.check_deadline(expires,now=self.now)),patch.object(m.asyncio,'sleep',new=AsyncMock(side_effect=self.sleep))]
  for p in self.patches:p.start();self.addCleanup(p.stop)
  self.rating={'mid':'528','peer_id':m.TARGET_PEER,'dir':'in','text':'Пожалуйста, оцените мою работу!','buttons':['★★★★★']}
  self.menu={**self.rating,'mid':'529','text':'Вижу, что вы откликались на несколько вакансий. По какой из них продолжить диалог?','buttons':['1. Аналитик']}
 async def sleep(self,seconds):self.now+=seconds
 async def test_auto_menu_never_sends_command(self):
  with patch.object(m,'scrape',new=AsyncMock(side_effect=[[self.rating],[self.menu]])),patch.object(m,'type_and_send',new=AsyncMock()) as send:
   await m.request_next_menu(None,False)
  send.assert_not_called()
 async def test_no_auto_menu_sends_once(self):
  with patch.object(m,'scrape',new=AsyncMock(return_value=[self.rating])),patch.object(m,'type_and_send',new=AsyncMock()) as send:
   await m.request_next_menu(None,False);await m.request_next_menu(None,False)
  send.assert_awaited_once_with(None,'/change_vacancy',False);self.assertEqual(m.PROGRESS['menu_request']['status'],'confirmed')
 async def test_changed_question_defers_to_new_message_without_retry(self):
  with patch.object(m,'scrape',new=AsyncMock(side_effect=[[self.rating],[self.rating],[self.menu]])) as scrape,patch.object(m,'type_and_send',new=AsyncMock(side_effect=guard.QuestionChanged('changed'))) as send:
   await m.request_next_menu(None,False)
  self.assertEqual(scrape.await_count,3);self.assertEqual(send.await_count,1);self.assertEqual(m.PROGRESS['menu_request']['status'],'not_dispatched')
 async def test_foreign_chat_error_still_stops(self):
  with patch.object(m,'scrape',new=AsyncMock(return_value=[self.rating])),patch.object(m,'type_and_send',new=AsyncMock(side_effect=m.NeedsDecision('Адресат изменился'))):
   with self.assertRaises(m.NeedsDecision):await m.request_next_menu(None,False)
 async def test_uncertain_send_is_never_retried(self):
  m.PROGRESS['menu_request']={'interview_key':'hh:12','status':'attempting'}
  with patch.object(m,'scrape',new=AsyncMock()) as scrape,patch.object(m,'type_and_send',new=AsyncMock()) as send:await m.request_next_menu(None,False)
  scrape.assert_not_called();send.assert_not_called()
 async def test_preview_does_not_send_or_wait(self):
  with patch.object(m,'scrape',new=AsyncMock()) as scrape,patch.object(m,'type_and_send',new=AsyncMock()) as send:await m.request_next_menu(None,True)
  scrape.assert_not_called();send.assert_not_called()
 async def test_unexpected_new_question_is_returned_to_main_loop(self):
  message={**self.rating,'text':'Новый вопрос','buttons':[]}
  with patch.object(m,'scrape',new=AsyncMock(return_value=[message])),patch.object(m,'type_and_send',new=AsyncMock()) as send:await m.request_next_menu(None,False)
  send.assert_not_called()
 async def test_exact_send_guard_failure_is_classified_not_dispatched(self):
  page=Mock();page.evaluate=AsyncMock(return_value={'ok':False,'reason':'Question already answered or changed'})
  with self.assertRaises(guard.QuestionChanged):await guard.dispatch(page,guard.SEND_JS,{})
 async def test_other_guard_failures_remain_fatal(self):
  page=Mock();page.evaluate=AsyncMock(return_value={'ok':False,'reason':'Peer changed'})
  try:await guard.dispatch(page,guard.SEND_JS,{})
  except guard.QuestionChanged:self.fail('Recipient failure must not be recoverable')
  except m.NeedsDecision:pass
  else:self.fail('Missing recipient failure')

from test_recipient_safety import RecipientSafetyTests
class MenuDraftBrowserTests(unittest.IsolatedAsyncioTestCase):
 asyncSetUp=RecipientSafetyTests.asyncSetUp
 asyncTearDown=RecipientSafetyTests.asyncTearDown
 async def test_changed_question_clears_only_our_unsent_command(self):
  with tempfile.TemporaryDirectory() as td,patch.object(m,'ensure_telegram_contact'),patch.object(m,'run_status'):
   m.STATE_PATH=Path(td)/'state.json';m.PROGRESS={'actions':{}};m.WEB_DEADLINE=guard.time.time()+120
   m.CURRENT_MESSAGE=m.fingerprint((await m.scrape(self.page))[-1])
   await self.page.evaluate("""() => {document.querySelector('.input-message-input').addEventListener('input',()=>{if(window.changed)return;window.changed=true;const b=document.createElement('div');b.className='bubble is-in';b.dataset.mid='2';b.innerHTML='<div class="message">Новое меню вакансий</div>';document.querySelector('.bubbles').append(b);});}""")
   with self.assertRaises(guard.QuestionChanged):await m.type_and_send(self.page,'/change_vacancy',False)
   self.assertEqual(await self.page.evaluate('sent'),[])
   self.assertEqual(await self.page.locator('.input-message-input').inner_text(),'')
   self.assertEqual(list(m.PROGRESS['actions'].values()),['not_dispatched'])

 async def test_changed_question_clears_only_our_unsent_regular_reply(self):
  with tempfile.TemporaryDirectory() as td,patch.object(m,'ensure_telegram_contact'),patch.object(m,'run_status'):
   m.STATE_PATH=Path(td)/'state.json';m.PROGRESS={'actions':{}};m.WEB_DEADLINE=guard.time.time()+120
   m.CURRENT_MESSAGE=m.fingerprint((await m.scrape(self.page))[-1])
   await self.page.evaluate("""() => {document.querySelector('.input-message-input').addEventListener('input',()=>{if(window.changed)return;window.changed=true;const b=document.createElement('div');b.className='bubble is-in';b.dataset.mid='2';b.innerHTML='<div class="message">Новый вопрос</div>';document.querySelector('.bubbles').append(b);});}""")
   with self.assertRaises(guard.QuestionChanged):await m.type_and_send(self.page,'Ответ на предыдущий вопрос',False)
   self.assertEqual(await self.page.evaluate('sent'),[]);self.assertEqual(await self.page.locator('.input-message-input').inner_text(),'')
   self.assertEqual(list(m.PROGRESS['actions'].values()),['not_dispatched'])
 async def test_changed_question_preserves_draft_edited_by_user(self):
  with tempfile.TemporaryDirectory() as td,patch.object(m,'ensure_telegram_contact'),patch.object(m,'run_status'):
   m.STATE_PATH=Path(td)/'state.json';m.PROGRESS={'actions':{}};m.WEB_DEADLINE=guard.time.time()+120
   m.CURRENT_MESSAGE=m.fingerprint((await m.scrape(self.page))[-1])
   await self.page.evaluate("""() => {document.querySelector('.input-message-input').addEventListener('input',()=>{if(window.changed)return;window.changed=true;document.querySelector('.input-message-input').textContent='Черновик пользователя';const b=document.createElement('div');b.className='bubble is-in';b.dataset.mid='2';b.innerHTML='<div class="message">Новый вопрос</div>';document.querySelector('.bubbles').append(b);});}""")
   with self.assertRaises(guard.QuestionChanged):await m.type_and_send(self.page,'Ответ на предыдущий вопрос',False)
   self.assertEqual(await self.page.evaluate('sent'),[]);self.assertEqual(await self.page.locator('.input-message-input').inner_text(),'Черновик пользователя')

if __name__=='__main__':unittest.main()
