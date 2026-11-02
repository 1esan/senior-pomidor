import asyncio,importlib.util,json,logging,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import AsyncMock,Mock,patch
STAGE=Path(__file__).resolve().parents[1];REAL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REAL));sys.path.insert(0,str(STAGE))
import interview_catalog as c
import interview_flow as f
import autonomous_runtime as a
from employer_guard import ContactBlocked
with patch('logging.FileHandler',return_value=logging.NullHandler()):
 spec=importlib.util.spec_from_file_location('upgraded_giga',STAGE/'giga-bot.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def item(vid,title='Системный аналитик',description=''):
 return {'id':str(vid),'name':title,'company':'СБЕР','employer_id':'3529','negotiation_id':'n'+str(vid),'description':description,'verified_at':time.time()}
def bubble(mid,entries,next_page=False):
 buttons=[f'{i+1}. {title}' for i,title in enumerate(entries)]
 return {'peer_id':m.TARGET_PEER,'mid':str(mid),'dir':'in','text':'Вижу, что вы откликались на несколько вакансий. По какой из них продолжить диалог?\n\n'+'\n\n'.join(label+'\nОписание.' for label in buttons),'buttons':buttons+(['Далее'] if next_page else []),'links':[],'section_links':{}}

class CatalogTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)
 def test_five_rows_and_duplicate_titles_keep_separate_links(self):
  b=bubble(1,['СА','СА','Третий','Четвёртый','Пятый'],True);b['section_links']={'1':['https://rabota.sber.ru/search/111'],'2':['https://rabota.sber.ru/search/222']}
  rows=c.numbered_entries(b);self.assertEqual(len(rows),5);self.assertEqual(rows[1]['links'],b['section_links']['2']);self.assertEqual(rows[4]['number'],'5')
 def test_unique_invited_title_matches_without_manual_binding(self):
  match,proof=c.match_entry({'title':'Системный аналитик (AI sales)','links':[]},[item(1,'Системный аналитик (AI sales)'),item(2)])
  self.assertEqual(match['id'],'1');self.assertEqual(proof,'unique_invited_title')
 def test_equal_titles_require_evidence(self):
  self.assertIsNone(c.match_entry({'title':'Системный аналитик','links':[]},[item(1),item(2)])[0])
 def test_official_id_is_row_scoped(self):
  candidates=[{**item(1),'official_ids':['111']},{**item(2),'official_ids':['222']}]
  match,_=c.match_entry({'title':'Системный аналитик','links':['https://rabota.sber.ru/search/222']},candidates);self.assertEqual(match['id'],'2')
 def test_public_description_requires_unique_long_fragments(self):
  d=' '.join('уникальноеслово'+str(i) for i in range(40))
  candidates=[item(1,description=d),item(2,description=' '.join('другоеслово'+str(i) for i in range(40)))]
  self.assertEqual(c.description_match('Вакансия '+d,candidates)['id'],'1')
  self.assertIsNone(c.description_match(d,[item(1,description=d),item(2,description=d)]))
 def test_untrusted_links_are_rejected(self):
  for url in ['http://rabota.sber.ru/search/111','https://rabota.sber.ru.evil.org/search/111','https://127.0.0.1/search/111','https://rabota.sber.ru/other/111']:
   self.assertIsNone(c.official_id(url))
 def test_new_own_invitation_appears_without_binding_and_pagination(self):
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);v={'id':'7','name':'СА','description':'Задачи','employer':{'id':'3529','name':'СБЕР'}}
   def read(path):
    if path.startswith('/negotiations?'):
     return {'pages':2,'items':[] if 'page=0&' in path or 'archived' in path else [{'id':'n7','vacancy':v}]}
    if path.startswith('/negotiations/n7/messages'):
     return {'pages':1,'items':[{'author':{'participant_type':'employer'},'text':'https://t.me/Giga_recruiter_bot?start=private'}]}
    if path=='/vacancies/7':return v
    raise AssertionError(path)
   with patch.object(c,'ensure_contact'):
    catalog=c.discover(base,read);self.assertEqual([i['id'] for i in catalog['items']],['7']);self.assertTrue(catalog['complete'])
   c.discover(base,Mock(side_effect=AssertionError('cache was ignored')))
 def test_applicant_link_does_not_enter_queue(self):
  with tempfile.TemporaryDirectory() as td,patch.object(c,'ensure_contact'):
   v={'id':'7','name':'СА','employer':{'id':'3529','name':'СБЕР'}}
   def read(path):
    if path.startswith('/negotiations?'):return {'pages':1,'items':[{'id':'n7','vacancy':v}]}
    return {'pages':1,'items':[{'author':{'participant_type':'applicant'},'text':'https://t.me/Giga_recruiter_bot?start=private'}]}
   self.assertEqual(c.discover(Path(td),read)['items'],[])
 def test_manual_switch_cannot_reuse_old_generic_scope(self):
  catalog={'items':[item(1),item(2,'Системный аналитик (Мобильное приложение)')]}
  actual=c.scope_from_intro('Получил Ваш отклик на позицию Системный аналитик(Мобильное приложение).',catalog,item(1))
  self.assertEqual(actual['id'],'2')
  with self.assertRaises(a.NeedsDecision):c.scope_from_intro('Получил Ваш отклик на позицию Системный аналитик.',{'items':[item(1),item(2)]},{**item(1),'selection':{'label':'Старая кнопка'}})
 def test_legacy_completion_is_not_reported_as_verified(self):
  scope,label,unknown=c.select_entry(self.base,bubble(1,['СА']),{'completed_interviews':{'hh:1':{'legacy_identity_unverified':True}}},{'items':[item(1,'СА')]})
  self.assertIsNone(scope);self.assertEqual(unknown[0]['reason'],'legacy_completion_needs_review')
 def test_manual_alias_still_requires_own_invitation_and_correct_employer(self):
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);path=base/'.state/telegram-bindings.json';path.parent.mkdir();path.write_text(json.dumps({'Моя подпись':{'vacancy_id':'1','employer_id':'3529'}}))
   scope,_,_=c.select_entry(base,bubble(1,['Моя подпись']),{}, {'items':[item(1)]})
   self.assertEqual(scope['id'],'1')
   scope,_,_=c.select_entry(base,bubble(1,['Моя подпись']),{}, {'items':[]})
   self.assertIsNone(scope)
 def test_duplicate_generic_labels_require_row_links_even_with_one_exact_title(self):
  b=bubble(1,['Системный аналитик','Системный аналитик']);b['section_links']={'1':['https://rabota.sber.ru/search/111'],'2':['https://rabota.sber.ru/search/222']}
  catalog={'items':[{**item(1),'official_ids':['111']},{**item(2,'Middle аналитик'),'official_ids':['222']}]}
  scope,label,unknown=c.select_entry(self.base,b,{'completed_interviews':{'hh:1':{}}},catalog)
  self.assertEqual(scope['id'],'2');self.assertEqual(label,'2. Системный аналитик')
 def test_senior_strategy_is_preserved(self):
  catalog={'items':[item(1,'СА'),item(2,'Senior аналитик')]}
  scope,label,_=c.select_entry(self.base,bubble(1,['СА','Senior аналитик']),{},catalog,strategy='senior')
  self.assertEqual(scope['id'],'2')
 def test_unreachable_public_page_does_not_delay_unique_known_title(self):
  b=bubble(1,['Известный аналитик','Системный аналитик']);b['section_links']={'2':['https://rabota.sber.ru/search/222']}
  fetch=Mock(side_effect=AssertionError('Known choice should not wait for public site'))
  scope,_,_=c.select_entry(self.base,b,{}, {'items':[item(1,'Известный аналитик'),item(2),item(3)]},fetch=fetch)
  self.assertEqual(scope['id'],'1');fetch.assert_not_called()
 def test_duplicate_rows_do_not_select_same_hh_id_twice(self):
  scope,label,unknown=c.select_entry(self.base,bubble(1,['СА','СА']),{}, {'items':[item(1,'СА')]})
  self.assertIsNone(scope);self.assertEqual(len(unknown),2)
 def test_cache_does_not_remove_local_employer_guard(self):
  scope=item(1);current={'vacancy_id':'1','name':scope['name'],'company':'СБЕР'}
  with patch.object(a,'ensure_contact') as guard,patch.object(a,'hh_read_json') as read:
   a.fresh_guard(scope,current);guard.assert_called_once();read.assert_not_called()
  with patch.object(a,'ensure_contact',side_effect=ContactBlocked('Запрет')):
   with self.assertRaises(ContactBlocked):a.fresh_guard(scope,current)
 def test_quarantines_legacy_memory_not_completion(self):
  with tempfile.TemporaryDirectory() as td:
   state={'active_context':{'key':'hh:1','messages':[{'content':'Смешанные данные'}]},'current':{'vacancy_id':'1'},'completed_interviews':{'hh:2':{}}}
   path=Path(td)/'web-live.json';f.migrate_context(state,path)
   self.assertEqual(state['active_context'],{});self.assertTrue(state['completed_interviews']['hh:2']['legacy_identity_unverified']);self.assertTrue((Path(td)/'web-live-legacy-context.json').exists())
 def test_completion_phrase_and_rating(self):
  self.assertTrue(a.interview_finished('Спасибо за интервью! Передам итоги рекрутеру.'))
  self.assertTrue(f.rating_request({'buttons':['★☆☆☆☆','★★★★★']}));self.assertFalse(f.rating_request({'buttons':['Да','Нет']}))

class FlowTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.temp=tempfile.TemporaryDirectory();m.STATE_PATH=Path(self.temp.name)/'state.json';m.PROGRESS={'actions':{},'completed_interviews':{},'context_schema':2};m.CUR_VACANCY.clear();m._history.clear();m.PINNED_VACANCY=None;m.AUTO_NEXT=True;m.AUTONOMOUS=False;m.INTERVIEW_COMPLETED=False
  self.status=patch.object(m,'run_status');self.status.start()
 async def asyncTearDown(self):self.status.stop();self.temp.cleanup()
 async def test_reaches_third_page_of_five_without_false_completion(self):
  pages=[bubble(10,['СА'+str(i) for i in range(5)],True),bubble(10,['СА'+str(i) for i in range(5,10)],True),bubble(10,['СА'+str(i) for i in range(10,15)])]
  catalog={'items':[item(14,'СА14')],'complete':True}
  clicks=AsyncMock(return_value=True)
  with patch.object(m,'get_catalog',return_value=catalog),patch.object(m,'fresh_guard'),patch.object(m,'human_pause',new=AsyncMock()),patch.object(m,'click_button',new=clicks),patch.object(m,'scrape',new=AsyncMock(side_effect=[[pages[1]],[pages[2]]])):
   await m.handle_menu(None,pages[0],False)
  self.assertEqual([x.args[1] for x in clicks.await_args_list],['Далее','Далее','5. СА14']);self.assertEqual(m.CUR_VACANCY['vacancy_id'],'14');self.assertFalse(m.INTERVIEW_COMPLETED)
 async def test_wrapping_unknown_pages_stops_honestly(self):
  first=bubble(10,['Неизвестная'],True);second=bubble(10,['Другая неизвестная'],True)
  with patch.object(m,'get_catalog',return_value={'items':[],'complete':True}),patch.object(m,'click_button',new=AsyncMock(return_value=True)),patch.object(m,'scrape',new=AsyncMock(side_effect=[[second],[first]])):
   with self.assertRaisesRegex(a.NeedsDecision,'Не удалось сопоставить'):await m.handle_menu(None,first,False)
  self.assertFalse(m.INTERVIEW_COMPLETED)
 async def test_preview_never_flips_real_pages(self):
  with patch.object(m,'get_catalog',return_value={'items':[],'complete':True}),patch.object(m,'click_button',new=AsyncMock()) as click:
   await m.handle_menu(None,bubble(1,['Нет в очереди'],True),True)
  click.assert_not_called()
 async def test_answer_stop_and_resume_same_interview_preserves_context(self):
  intro={'peer_id':m.TARGET_PEER,'mid':'310','dir':'in','buttons':[],'text':'Получил Ваш отклик на позицию Р7-Офис.'}
  catalog={'items':[item(1,'Р7-Офис')],'complete':True}
  with patch.object(m,'get_catalog',return_value=catalog):await m.establish_interview(intro)
  m._remember('assistant','Ранее описал интеграции офисного пакета и API.')
  saved=json.loads(m.STATE_PATH.read_text())
  # A new process has persisted state, but no runtime scope or in-memory history.
  m.PINNED_VACANCY=None;m._history.clear();m.CUR_VACANCY.clear();m.CUR_VACANCY.update(saved['current']);m.PROGRESS=saved
  with patch.object(m,'get_catalog',return_value=catalog):await m.establish_interview(intro)
  self.assertEqual(m.PINNED_VACANCY['id'],'1');self.assertEqual(m._history,[{'role':'assistant','content':'Ранее описал интеграции офисного пакета и API.'}])
  next_question={'peer_id':m.TARGET_PEER,'mid':'315','dir':'in','buttons':[],'text':'Какие офисные пакеты использовали?'}
  with patch.object(m,'contact_reason',return_value=None),patch.object(m,'ensure_telegram_contact'),patch.object(m,'resolve_company',return_value=None),patch.object(m,'ollama_chat',return_value='Использовал офисные пакеты для подготовки документов и таблиц.'),patch.object(m,'human_pause',new=AsyncMock()),patch.object(m,'type_and_send',new=AsyncMock()) as send:
   await m.handle_last(None,next_question,False)
  send.assert_awaited_once();self.assertEqual(send.await_args.args[1],'Использовал офисные пакеты для подготовки документов и таблиц.')
  self.assertIn('Ранее описал',m._history[0]['content'])
 async def test_same_generic_intro_restores_verified_id_after_restart(self):
  intro={'peer_id':m.TARGET_PEER,'mid':'310','dir':'in','buttons':[],'text':'Получил Ваш отклик на позицию Системный аналитик.'}
  m.CUR_VACANCY.update(m.current_scope_record(item(2),m.fingerprint(intro)))
  m.PROGRESS['current']=dict(m.CUR_VACANCY);m.PROGRESS['active_context']={'key':'hh:2','messages':[{'role':'assistant','content':'Детали второго интервью'}]};m.PROGRESS['awaiting_menu']=True
  with patch.object(m,'get_catalog',return_value={'items':[item(1),item(2)]}):await m.establish_interview(intro)
  self.assertEqual(m.PINNED_VACANCY['id'],'2');self.assertEqual(m._history[0]['content'],'Детали второго интервью');self.assertTrue(m.PROGRESS['awaiting_menu'])
 async def test_manual_intro_isolates_memory(self):
  m.CUR_VACANCY.update(vacancy_id='1',intro_fingerprint='old');m.PROGRESS['active_context']={'key':'hh:1','messages':[{'role':'assistant','content':'Секрет прошлого интервью'}]};m.PINNED_VACANCY=item(1)
  b={'peer_id':m.TARGET_PEER,'mid':'20','dir':'in','buttons':[],'text':'Получил Ваш отклик на позицию Мобильный аналитик.'}
  with patch.object(m,'get_catalog',return_value={'items':[item(1),item(2,'Мобильный аналитик')]}):await m.establish_interview(b)
  self.assertEqual(m.CUR_VACANCY['vacancy_id'],'2');self.assertEqual(m._history,[]);self.assertEqual(m.PROGRESS['active_context']['key'],'hh:2')
 async def test_rating_skips_model_and_requests_menu(self):
  m.PINNED_VACANCY=item(1);m.CUR_VACANCY.update(m.current_scope_record(m.PINNED_VACANCY,m.TARGET_PEER+':1:abc'));m.PROGRESS['awaiting_menu']=True
  b={'mid':'20','buttons':['★☆☆☆☆','★★★★★'],'text':'Пожалуйста, оцените мою работу!'}
  with patch.object(m,'ollama_chat') as model,patch.object(m,'request_next_menu',new=AsyncMock()) as send:
   await m.handle_last(None,b,False)
  model.assert_not_called();send.assert_awaited_once_with(None,False);self.assertIn('hh:1',m.PROGRESS['completed_interviews'])
 async def test_completed_interviews_are_skipped_across_all_pages(self):
  m.PROGRESS['completed_interviews']={'hh:1':{},'hh:2':{}}
  first=bubble(10,['Первый'],True);second=bubble(10,['Второй'])
  with patch.object(m,'get_catalog',return_value={'items':[item(1,'Первый'),item(2,'Второй')],'complete':True}),patch.object(m,'click_button',new=AsyncMock(return_value=True)) as click,patch.object(m,'scrape',new=AsyncMock(return_value=[second])):
   await m.handle_menu(None,first,False)
  self.assertTrue(m.INTERVIEW_COMPLETED);self.assertEqual(click.await_count,1);self.assertEqual(click.await_args.args[1],'Далее')
 async def test_new_generic_intro_cannot_reuse_old_selection(self):
  m.PINNED_VACANCY={**item(1),'selection':{'label':'Старая кнопка'}}
  m.CUR_VACANCY.update(vacancy_id='1',intro_fingerprint=m.TARGET_PEER+':1:old')
  b={'peer_id':m.TARGET_PEER,'mid':'20','dir':'in','buttons':[],'text':'Получил Ваш отклик на позицию Системный аналитик.'}
  with patch.object(m,'get_catalog',return_value={'items':[item(1),item(2)]}):
   with self.assertRaises(a.NeedsDecision):await m.establish_interview(b)
 async def test_confirmed_menu_selection_can_bind_next_generic_intro(self):
  m.PROGRESS['pending_selection']={**item(2),'selection':{'menu_fingerprint':m.TARGET_PEER+':10:menu','selected_at':time.time(),'proof':'official_id','label':'2. Системный аналитик'}}
  m.PROGRESS['actions'][m.TARGET_PEER+':10:menu:button-native:2. Системный аналитик']='confirmed'
  b={'peer_id':m.TARGET_PEER,'mid':'20','dir':'in','buttons':[],'text':'Получил Ваш отклик на позицию Системный аналитик.'}
  with patch.object(m,'get_catalog',return_value={'items':[item(1),item(2)]}):await m.establish_interview(b)
  self.assertEqual(m.CUR_VACANCY['vacancy_id'],'2');self.assertNotIn('pending_selection',m.PROGRESS)
 async def test_old_intro_before_pending_selection_cannot_bind(self):
  m.PROGRESS['pending_selection']={**item(2),'selection':{'menu_fingerprint':m.TARGET_PEER+':30:menu','selected_at':time.time(),'label':'2. Системный аналитик'}}
  b={'peer_id':m.TARGET_PEER,'mid':'20','dir':'in','buttons':[],'text':'Получил Ваш отклик на позицию Системный аналитик.'}
  with patch.object(m,'get_catalog',return_value={'items':[item(1),item(2)]}):
   with self.assertRaises(a.NeedsDecision):await m.establish_interview(b)
 async def test_pending_selection_filters_unique_old_intro_without_wiping_choice(self):
  selected={**item(2),'selection':{'menu_fingerprint':m.TARGET_PEER+':449:menu','selected_at':time.time(),'proof':'official_id','label':'1. Системный аналитик'}}
  m.PROGRESS['actions'][m.TARGET_PEER+':449:menu:button-native:1. Системный аналитик']='confirmed'
  m.PROGRESS['pending_selection']=selected;m.CUR_VACANCY.update(m.current_scope_record(selected));m.PINNED_VACANCY=selected
  old={'peer_id':m.TARGET_PEER,'mid':'439','dir':'in','buttons':[],'text':'Получил Ваш отклик на позицию СФР.'}
  ack={**old,'mid':'449','text':'Спасибо за выбор вакансии! Дайте мне несколько секунд — и мы начнем диалог 👍'}
  self.assertEqual(m.visible_interview_intros([old,ack]),[])
  with patch.object(m,'get_catalog') as catalog,patch.object(m,'ollama_chat') as model:
   await m.handle_last(None,ack,False)
   catalog.assert_not_called();model.assert_not_called()
  self.assertEqual(m.PROGRESS['pending_selection']['id'],'2');self.assertEqual(m.CUR_VACANCY['vacancy_id'],'2')
 async def test_new_generic_intro_after_ack_keeps_selected_id_across_restart(self):
  selected={**item(2),'selection':{'menu_fingerprint':m.TARGET_PEER+':449:menu','selected_at':time.time(),'proof':'official_id','label':'1. Системный аналитик'}}
  m.PROGRESS['actions'][m.TARGET_PEER+':449:menu:button-native:1. Системный аналитик']='confirmed'
  m.PROGRESS.update(pending_selection=selected,current=m.current_scope_record(selected),active_context={'key':'hh:2','messages':[]})
  m.CUR_VACANCY.update(m.PROGRESS['current']);m.PINNED_VACANCY=None
  old={'peer_id':m.TARGET_PEER,'mid':'439','dir':'in','buttons':[],'text':'Получил Ваш отклик на позицию СФР.'}
  new={**old,'mid':'450','text':'Получил Ваш отклик на позицию Системный аналитик.'}
  intros=m.visible_interview_intros([old,new]);self.assertEqual(intros,[new])
  with patch.object(m,'get_catalog',return_value={'items':[item(1),item(2),item(3,'СФР')]}):await m.establish_interview(intros[-1])
  self.assertEqual(m.CUR_VACANCY['vacancy_id'],'2');self.assertEqual(m.CUR_VACANCY['intro_mid'],'450');self.assertNotIn('pending_selection',m.PROGRESS)
  self.assertEqual(m.PROGRESS['active_context'],{'key':'hh:2','messages':[]})
 async def test_direct_old_unique_intro_is_rejected_before_catalog_and_preserves_pending(self):
  selected={**item(2),'selection':{'menu_fingerprint':m.TARGET_PEER+':449:menu','selected_at':time.time()}}
  m.PROGRESS['pending_selection']=selected
  old={'peer_id':m.TARGET_PEER,'mid':'439','dir':'in','buttons':[],'text':'Получил Ваш отклик на позицию СФР.'}
  with patch.object(m,'get_catalog') as catalog:
   with self.assertRaises(a.NeedsDecision):await m.establish_interview(old)
   catalog.assert_not_called()
  self.assertEqual(m.PROGRESS['pending_selection'],selected)
 async def test_same_menu_mid_intro_is_not_treated_as_new_interview(self):
  m.PROGRESS['pending_selection']={**item(2),'selection':{'menu_fingerprint':m.TARGET_PEER+':449:menu','selected_at':time.time()}}
  b={'peer_id':m.TARGET_PEER,'mid':'449','dir':'in','buttons':[],'text':'Получил Ваш отклик на позицию Системный аналитик.'}
  self.assertEqual(m.visible_interview_intros([b]),[])
 async def test_completion_notice_before_rating_and_old_notice_not_reused(self):
  old={'mid':'5','peer_id':m.TARGET_PEER,'dir':'in','text':'Спасибо за интервью!','buttons':[]}
  new={**old,'mid':'25'};rating={'mid':'26','dir':'in','text':'Оцените','buttons':['★★★★★']}
  notices=f.terminal_notices([old,new,rating],set(),{'intro_mid':'20'})
  self.assertEqual(notices,[new])
 async def test_ambiguous_intro_does_not_load_or_answer_with_old_memory(self):
  m.PINNED_VACANCY=item(1);m.CUR_VACANCY.update(vacancy_id='1',intro_fingerprint='old');m._history[:]=[{'role':'assistant','content':'Другой разговор'}]
  b={'peer_id':m.TARGET_PEER,'mid':'20','dir':'in','buttons':[],'text':'Получил Ваш отклик на позицию Системный аналитик.'}
  with patch.object(m,'get_catalog',return_value={'items':[item(1),item(2)]}),patch.object(m,'ollama_chat') as model:
   with self.assertRaises(a.NeedsDecision):await m.handle_last(None,b,False)
  model.assert_not_called()
if __name__=='__main__':unittest.main()
