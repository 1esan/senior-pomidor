import importlib.util,json,logging,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import AsyncMock,Mock,patch
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
import interview_catalog as c
with patch('logging.FileHandler',return_value=logging.NullHandler()):
 spec=importlib.util.spec_from_file_location('stall_engine',BASE/'giga-bot.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

REAL_TYPE_AND_SEND=m.type_and_send

def item(vid,title='Системный аналитик'):
 return {'id':str(vid),'name':title,'company':'СБЕР','employer_id':'3529','negotiation_id':'n'+str(vid),'description':''}
def bubble(mid=20,direction='out',text='Мой ответ'):
 return {'peer_id':m.TARGET_PEER,'mid':str(mid),'dir':direction,'text':text,'buttons':[]}
class RecoveryTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);m.STATE_PATH=Path(self.temp.name)/'state.json'
  self.scope=item(2);m.CUR_VACANCY.clear();m.CUR_VACANCY.update(m.current_scope_record(self.scope,m.TARGET_PEER+':10:old'));m.PINNED_VACANCY=self.scope
  self.history=[{'role':'assistant','content':'Уже описал Kafka'}];m._history[:]=self.history
  m.PROGRESS={'actions':{},'current':dict(m.CUR_VACANCY),'active_context':{'key':'hh:2','messages':list(self.history)},'completed_interviews':{}}
  m.WEB_DEADLINE=time.time()+1000;m.CURRENT_MESSAGE=m.fingerprint(bubble(19,'in','Вопрос'))
  self.last=bubble();self.handled={m.CURRENT_MESSAGE}
  for name,value in [('assert_target',AsyncMock()),('scrape',AsyncMock(side_effect=lambda page:[self.last])),('get_catalog',Mock(return_value={'items':[self.scope]})),('fresh_guard',Mock()),('run_status',Mock()),('type_and_send',AsyncMock())]:
   p=patch.object(m,name,value);p.start();self.addCleanup(p.stop)
 def reset_command_fixture(self,legacy=False):
  source=bubble(20,'out','Мой ответ');command=bubble(21,'out','/change_vacancy')
  fp=m.fingerprint(source);key=fp+':text:'+m.hashlib.sha256(b'/change_vacancy').hexdigest()
  m.PROGRESS['stall_recovery']={'vacancy_id':'2','status':'confirmed','source_fingerprint':fp}
  if not legacy:m.PROGRESS['stall_recovery'].update(command_mid='21',command_action_key=key)
  m.PROGRESS['actions'][key]='confirmed'
  m.PROGRESS['pending_selection']={**self.scope,'selection':{'menu_fingerprint':m.TARGET_PEER+':15:menu','label':'1. Аналитик'}}
  return source,command,key
 async def test_real_send_records_exact_reset_mid_and_clears_pending(self):
  source,command,key=self.reset_command_fixture();m.PROGRESS['stall_recovery']['status']='attempting';m.PROGRESS['actions'].pop(key)
  m.CURRENT_MESSAGE=m.fingerprint(source);self.last=source;page=Mock();page.locator.return_value.fill=AsyncMock()
  with patch.object(m,'ensure_telegram_contact'),patch.object(m,'require_empty_editor',new=AsyncMock()),patch.object(m,'dispatch',new=AsyncMock(return_value=m.TARGET_PEER)),patch.object(m,'confirm_outgoing',new=AsyncMock(return_value=command)):
   await REAL_TYPE_AND_SEND(page,'/change_vacancy',False,recovery=True)
  record=m.PROGRESS['stall_recovery'];self.assertEqual(record['command_mid'],'21');self.assertEqual(record['command_action_key'],key);self.assertEqual(record['status'],'confirmed')
  self.assertNotIn('pending_selection',m.PROGRESS);self.assertEqual(m.PROGRESS['actions'][key],'confirmed')
 async def test_own_confirmed_reset_does_not_trip_manual_change_guard(self):
  source,command,_=self.reset_command_fixture()
  self.assertEqual(m.visible_interview_intros([source,command]),[])
  self.assertTrue(m.awaiting_recovery_menu([source,command]));self.assertEqual(m._history,self.history)
 async def test_legacy_confirmed_reset_is_recognized_after_restart(self):
  source,command,_=self.reset_command_fixture(legacy=True)
  self.assertEqual(m.confirmed_recovery_command([source,command]),'21')
  self.assertEqual(m.visible_interview_intros([source,command]),[])
  self.assertTrue(m.awaiting_recovery_menu([source,command]))
 async def test_new_menu_unblocks_exact_reselection(self):
  source,command,_=self.reset_command_fixture()
  menu=bubble(22,'in','По какой из них продолжить диалог?');menu['buttons']=['1. Системный аналитик']
  self.assertFalse(m.awaiting_recovery_menu([source,command,menu]))
  self.assertEqual(m.visible_interview_intros([source,command,menu]),[])
 async def test_old_menu_does_not_count_as_reset_response(self):
  source,command,_=self.reset_command_fixture()
  old=bubble(19,'in','По какой из них продолжить диалог?');old['buttons']=['1. Аналитик']
  self.assertTrue(m.awaiting_recovery_menu([old,source,command]))
 async def test_manual_second_command_is_not_mistaken_for_own_reset(self):
  source,command,_=self.reset_command_fixture()
  with self.assertRaises(m.NeedsDecision):m.visible_interview_intros([source,command,bubble(22,'out','/change_vacancy')])
 async def test_manual_command_then_fresh_menu_allows_reselection(self):
  source,command,_=self.reset_command_fixture();manual=bubble(22,'out','/change_vacancy')
  menu=bubble(23,'in','По какой из них продолжить диалог?');menu['buttons']=['1. Системный аналитик']
  history=[source,command,manual,menu]
  self.assertEqual(m.visible_interview_intros(history),[]);self.assertFalse(m.awaiting_recovery_menu(history))
  scope={**self.scope,'selection':{'menu_fingerprint':m.fingerprint(menu),'selected_at':time.time(),'label':menu['buttons'][0],'proof':'official_id'}}
  async def confirm_choice(page,label,dry):
   m.PROGRESS['actions'][m.CURRENT_MESSAGE+':button-native:'+label]='confirmed';return True
  with patch.object(m,'select_entry',return_value=(scope,menu['buttons'][0],[])),patch.object(m,'click_button',new=AsyncMock(side_effect=confirm_choice)),patch.object(m,'human_pause',new=AsyncMock()):
   await m.handle_menu(None,menu,False)
  intro=bubble(24,'in','Получил Ваш отклик на позицию Новое название проекта.')
  self.assertEqual(m.visible_interview_intros(history+[intro]),[intro])
  await m.establish_interview(intro)
  self.assertEqual(m.CUR_VACANCY['vacancy_id'],'2');self.assertEqual(m._history,self.history)
 async def test_menu_before_manual_command_cannot_unblock_old_scope(self):
  source,command,_=self.reset_command_fixture();manual=bubble(23,'out','/change_vacancy')
  menu=bubble(22,'in','По какой из них продолжить диалог?');menu['buttons']=['1. Аналитик']
  with self.assertRaises(m.NeedsDecision):m.visible_interview_intros([source,command,manual,menu])
 async def test_intro_after_manual_change_needs_fresh_confirmed_selection(self):
  source,command,_=self.reset_command_fixture();manual=bubble(22,'out','/change_vacancy')
  menu=bubble(23,'in','По какой из них продолжить диалог?');menu['buttons']=['1. Аналитик']
  intro=bubble(24,'in','Получил Ваш отклик на позицию Системный аналитик.')
  with self.assertRaises(m.NeedsDecision):m.visible_interview_intros([source,command,manual,menu,intro])
 async def test_unconfirmed_reset_has_no_manual_guard_exemption(self):
  source,command,key=self.reset_command_fixture();m.PROGRESS['actions'][key]='submitted'
  with self.assertRaises(m.NeedsDecision):m.visible_interview_intros([source,command])
  with self.assertRaises(m.NeedsDecision):m.awaiting_recovery_menu([source,command])
 async def test_late_old_intro_not_rebound_before_reset_menu(self):
  source,command,_=self.reset_command_fixture();late=bubble(22,'in','Получил Ваш отклик на позицию Системный аналитик.')
  self.assertEqual(m.visible_interview_intros([source,command,late]),[])
  self.assertTrue(m.awaiting_recovery_menu([source,command,late]));self.assertEqual(m._history,self.history)
 async def test_old_reset_does_not_invalidate_new_confirmed_selection(self):
  source,command,_=self.reset_command_fixture();m.PROGRESS['stall_recovery']['status']='selecting'
  menu_fp=m.TARGET_PEER+':23:menu';selected={**self.scope,'selection':{'menu_fingerprint':menu_fp,'label':'1. Аналитик','proof':'official_id'}}
  m.PROGRESS['pending_selection']=selected;m.PROGRESS['actions'][menu_fp+':button-native:1. Аналитик']='confirmed'
  intro=bubble(24,'in','Получил Ваш отклик на позицию Другое название той же вакансии.')
  self.assertEqual(m.visible_interview_intros([source,command,intro]),[intro])
  await m.establish_interview(intro)
  self.assertEqual(m.CUR_VACANCY['vacancy_id'],'2');self.assertEqual(m._history,self.history);self.assertNotIn('stall_recovery',m.PROGRESS)
 async def test_three_resets_follow_six_ten_ten_minutes(self):
  base=time.time();clock=Mock(wraps=time);clock.time=Mock(return_value=base);m.WEB_DEADLINE=base+10000
  calls=[]
  async def send(page,text,dry,recovery=False):
   record=m.PROGRESS['stall_recovery'];calls.append((clock.time(),record['attempt']))
   key=record['source_fingerprint']+':text:'+m.hashlib.sha256(text.encode()).hexdigest()
   m.PROGRESS['actions'][key]='confirmed';self.last=bubble(int(self.last['mid'])+1,'out',text)
   record.update(command_mid=self.last['mid'],command_action_key=key,status='confirmed',confirmed_at=clock.time(),next_retry_at=clock.time()+600)
  m.type_and_send.side_effect=send
  with patch.object(m,'time',clock):
   self.assertEqual(m.recruiter_wait_deadline(base),base+360)
   clock.time.return_value=base+360;await m.recover_stalled_interview(None,False,self.handled)
   self.assertEqual(m.recruiter_wait_deadline(base+9000),base+960)
   clock.time.return_value=base+959;await m.recover_stalled_interview(None,False,self.handled);self.assertEqual(len(calls),1)
   clock.time.return_value=base+960;await m.recover_stalled_interview(None,False,self.handled)
   clock.time.return_value=base+1559;await m.recover_stalled_interview(None,False,self.handled);self.assertEqual(len(calls),2)
   clock.time.return_value=base+1560;await m.recover_stalled_interview(None,False,self.handled)
   self.assertEqual(calls,[(base+360,1),(base+960,2),(base+1560,3)])
   clock.time.return_value=base+2160
   with self.assertRaisesRegex(m.NeedsDecision,'Три сброса'):await m.recover_stalled_interview(None,False,self.handled)
  self.assertEqual(len(calls),3);self.assertEqual(m._history,self.history)
 async def test_reselection_does_not_restart_ten_minute_clock(self):
  _,_,_=self.reset_command_fixture();r=m.PROGRESS['stall_recovery'];r.update(attempt=1,started_at=1000,confirmed_at=1005,next_retry_at=1605,status='selecting')
  self.assertEqual(m.recruiter_wait_deadline(1500),1605)
  self.assertEqual(m.recruiter_wait_deadline(1900),1605)
 async def test_reply_settings_and_first_wait_are_updated(self):
  config=m.settings();self.assertEqual((config['reply_pause_min_seconds'],config['reply_pause_max_seconds']),(60,120));self.assertEqual(config['recruiter_wait_seconds'],360)
 async def test_recovery_resume_clears_backoff_for_next_question(self):
  m.PROGRESS['stall_recovery']={'vacancy_id':'2','status':'selecting','attempt':3,'next_retry_at':9999999999}
  menu_fp=m.TARGET_PEER+':22:menu';selected={**self.scope,'selection':{'menu_fingerprint':menu_fp,'label':'1. Аналитик','proof':'official_id'}}
  m.PROGRESS['pending_selection']=selected;m.PROGRESS['actions'][menu_fp+':button-native:1. Аналитик']='confirmed'
  await m.establish_interview(bubble(24,'in','Получил Ваш отклик на позицию Аналитик проекта.'))
  self.assertNotIn('stall_recovery',m.PROGRESS)
  self.assertEqual(m.recruiter_wait_deadline(1000),1360)
 async def test_expired_retry_gives_fresh_click_full_response_window(self):
  now=time.time();m.PROGRESS['stall_recovery']={'vacancy_id':'2','status':'selecting','next_retry_at':now-100,'attempt':1}
  menu=bubble(30,'in','По какой из них продолжить диалог?');menu['buttons']=['1. Системный аналитик']
  self.last=menu;m.CURRENT_MESSAGE=m.fingerprint(menu)
  with patch.object(m,'ensure_telegram_contact'),patch.object(m,'native_button',new=AsyncMock()),patch.object(m,'wait_for_new_message',new=AsyncMock(return_value=bubble(31,'in','Спасибо за выбор вакансии!'))) as wait:
   await m.click_button(None,menu['buttons'][0],False)
  self.assertGreaterEqual(wait.await_args.args[2],359)
  self.assertGreaterEqual(m.recruiter_wait_deadline(now),now+359)
  self.assertEqual(m.PROGRESS['stall_recovery']['next_retry_at'],now-100)
 async def test_changed_question_before_click_does_not_extend_timer_or_click(self):
  m.PROGRESS['stall_recovery']={'vacancy_id':'2','status':'selecting','next_retry_at':1000};m.CURRENT_MESSAGE='old-fingerprint'
  with patch.object(m,'ensure_telegram_contact'),patch.object(m,'native_button',new=AsyncMock()) as click:
   with self.assertRaises(m.QuestionChanged):await m.click_button(None,'1. Системный аналитик',False)
  click.assert_not_awaited();self.assertNotIn('button_response_until',m.PROGRESS['stall_recovery'])
  self.assertEqual(await m.refresh_changed_question(None),[self.last])
 async def test_refresh_failure_for_foreign_recipient_remains_fatal(self):
  m.assert_target.side_effect=m.NeedsDecision('foreign recipient')
  with self.assertRaises(m.NeedsDecision):await m.refresh_changed_question(None)
 async def test_verified_late_intro_ends_recovery_even_without_new_click(self):
  m.PROGRESS['stall_recovery']={'vacancy_id':'2','status':'selecting','attempt':2,'next_retry_at':1000}
  await m.establish_interview(bubble(40,'in','Получил Ваш отклик на позицию Системный аналитик.'))
  self.assertNotIn('stall_recovery',m.PROGRESS);self.assertEqual(m._history,self.history)
 async def test_main_loop_continues_to_new_message_after_question_changed(self):
  from contextlib import ExitStack
  from unittest.mock import MagicMock
  old=bubble(30,'in','По какой из них продолжить диалог?');old['buttons']=['1. Аналитик']
  new=bubble(31,'in','По какой из них продолжить диалог?');new['buttons']=['1. Новый аналитик']
  state={'actions':{},'completed_interviews':{},'context_schema':2,'current':{}}
  context=Mock();page=Mock();page.goto=AsyncMock();context.pages=[page];context.close=AsyncMock()
  pw=Mock();pw.chromium.launch_persistent_context=AsyncMock(return_value=context)
  manager=MagicMock();manager.__aenter__=AsyncMock(return_value=pw);manager.__aexit__=AsyncMock(return_value=False)
  seen=[]
  async def handler(page,message,dry):
   seen.append(message['mid'])
   if len(seen)==1:raise m.QuestionChanged('changed before dispatch')
   m.INTERVIEW_COMPLETED=True
  with ExitStack() as stack:
   for name,value in [('async_playwright',Mock(return_value=manager)),('ollama_alive',AsyncMock(return_value=True)),('wait_login',AsyncMock(return_value=True)),('bind_page',AsyncMock()),('wait_history',AsyncMock(return_value=[old])),('load_state',Mock(return_value=(m.STATE_PATH,state))),('scrape',AsyncMock(return_value=[new])),('handle_last',AsyncMock(side_effect=handler))]:stack.enter_context(patch.object(m,name,value))
   stack.enter_context(patch.object(m.sys,'argv',['giga-bot.py','--live','--minutes','1']))
   stack.enter_context(patch.object(m.asyncio,'sleep',new=AsyncMock()))
   m.INTERVIEW_COMPLETED=False
   await m.main()
  self.assertEqual(seen,['30','31']);self.assertIn(m.fingerprint(old),state['handled']);context.close.assert_awaited_once()
 async def test_confirmed_reset_keeps_history_and_exact_target(self):
  await m.recover_stalled_interview(None,False,self.handled)
  m.type_and_send.assert_awaited_once_with(None,'/change_vacancy',False,recovery=True)
  self.assertEqual(m.PROGRESS['stall_recovery']['vacancy_id'],'2');self.assertEqual(m.PROGRESS['stall_recovery']['status'],'confirmed');self.assertEqual(m._history,self.history)
 async def test_late_question_prevents_reset(self):
  self.last=bubble(21,'in','Следующий вопрос')
  await m.recover_stalled_interview(None,False,self.handled);m.type_and_send.assert_not_awaited()
 async def test_changed_message_before_dispatch_cancels_recovery(self):
  m.type_and_send.side_effect=m.QuestionChanged('changed')
  await m.recover_stalled_interview(None,False,self.handled)
  self.assertNotIn('stall_recovery',m.PROGRESS);self.assertEqual(m._history,self.history)
 async def test_uncertain_reset_delivery_never_repeats(self):
  m.type_and_send.side_effect=m.NeedsDecision('delivery unknown')
  with self.assertRaises(m.NeedsDecision):await m.recover_stalled_interview(None,False,self.handled)
  m.type_and_send.reset_mock()
  with self.assertRaises(m.NeedsDecision):await m.recover_stalled_interview(None,False,self.handled)
  m.type_and_send.assert_not_awaited()
 async def test_completed_interview_is_not_reopened(self):
  m.PROGRESS['completed_interviews']['hh:2']={}
  with self.assertRaises(m.NeedsDecision):await m.recover_stalled_interview(None,False,self.handled)
  m.type_and_send.assert_not_awaited()
 async def test_preview_never_sends(self):
  await m.recover_stalled_interview(None,True,self.handled);m.type_and_send.assert_not_awaited()
 async def test_foreign_chat_guard_remains_fatal(self):
  m.assert_target.side_effect=m.NeedsDecision('foreign peer')
  with self.assertRaises(m.NeedsDecision):await m.recover_stalled_interview(None,False,self.handled)
  m.type_and_send.assert_not_awaited()
 async def test_resumed_intro_preserves_active_interview_memory(self):
  menu_fp=m.TARGET_PEER+':22:menu';selected={**self.scope,'selection':{'menu_fingerprint':menu_fp,'selected_at':time.time(),'label':'2. Системный аналитик','proof':'verified_entry_identity'}}
  m.PROGRESS['stall_recovery']={'vacancy_id':'2','status':'selecting'};m.PROGRESS['pending_selection']=selected
  m.PROGRESS['actions'][menu_fp+':button-native:'+selected['selection']['label']]='confirmed'
  m.get_catalog.return_value={'items':[item(1),self.scope]}
  await m.establish_interview(bubble(24,'in','Давайте продолжим общение по вакансии Системный аналитик. Мы остановились на этом месте:\nВопрос'))
  self.assertEqual(m._history,self.history);self.assertNotIn('stall_recovery',m.PROGRESS);self.assertEqual(m.CUR_VACANCY['vacancy_id'],'2')
 async def test_wrong_resumed_vacancy_does_not_replace_memory(self):
  m.PROGRESS['stall_recovery']={'vacancy_id':'2','status':'selecting'}
  m.get_catalog.return_value={'items':[item(3,'Другой аналитик')]}
  with self.assertRaises(m.NeedsDecision):
   await m.establish_interview(bubble(24,'in','Получил Ваш отклик на позицию Другой аналитик.'))
  self.assertEqual(m._history,self.history);self.assertEqual(m.CUR_VACANCY['vacancy_id'],'2')
 async def test_new_normal_interview_still_clears_previous_memory(self):
  m.get_catalog.return_value={'items':[item(3,'Другой аналитик')]}
  await m.establish_interview(bubble(24,'in','Получил Ваш отклик на позицию Другой аналитик.'))
  self.assertEqual(m._history,[])
 async def test_recovery_paginates_before_selecting_exact_target(self):
  first=bubble(30,'in','Меню');first['buttons']=['Далее']
  second=bubble(32,'in','По какой из них продолжить диалог?');second['buttons']=['2. Системный аналитик']
  scope={**self.scope,'selection':{'menu_fingerprint':m.fingerprint(second),'selected_at':time.time(),'label':second['buttons'][0],'proof':'unique_invited_title'}}
  m.PROGRESS['stall_recovery']={'vacancy_id':'2','status':'confirmed'}
  m.scrape.side_effect=None;m.scrape.return_value=[second]
  with patch.object(m,'select_entry',side_effect=[(None,None,[]),(scope,second['buttons'][0],[])]) as select,patch.object(m,'click_button',new=AsyncMock(return_value=True)) as click,patch.object(m,'human_pause',new=AsyncMock()):
   await m.handle_menu(None,first,False)
  self.assertEqual(click.await_args_list[0].args[1],'Далее');self.assertEqual(click.await_args_list[1].args[1],second['buttons'][0])
  self.assertTrue(all(call.kwargs['required_id']=='2' for call in select.call_args_list));self.assertEqual(m._history,self.history)
 async def test_exact_recovery_target_never_falls_back_to_other_known_row(self):
  b={'peer_id':m.TARGET_PEER,'mid':'30','text':'1. Другая вакансия','buttons':['1. Другая вакансия'],'section_links':{}}
  scope,_,_=c.select_entry(Path(self.temp.name),b,{}, {'items':[item(1,'Другая вакансия'),self.scope]},required_id='2',fetch=lambda url:'')
  self.assertIsNone(scope)
 async def test_exact_target_fetches_even_if_another_row_is_already_known(self):
  description=' '.join('уникальноеслово'+str(i) for i in range(40));target={**self.scope,'description':description}
  b={'peer_id':m.TARGET_PEER,'mid':'30','text':'1. Другая вакансия\n\n2. Системный аналитик','buttons':['1. Другая вакансия','2. Системный аналитик'],'section_links':{'2':['https://www.rabota.ru/vacancy/123/']}}
  scope,_,_=c.select_entry(Path(self.temp.name),b,{}, {'items':[item(1,'Другая вакансия'),target,item(3)]},required_id='2',fetch=lambda url:description)
  self.assertEqual(scope['id'],'2')

if __name__=='__main__':unittest.main()
