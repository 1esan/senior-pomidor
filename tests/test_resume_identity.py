import importlib.util,logging,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
import interview_catalog as c
from autonomous_runtime import NeedsDecision
with patch('logging.FileHandler',return_value=logging.NullHandler()):
 spec=importlib.util.spec_from_file_location('resume_identity_engine',BASE/'giga-bot.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def item(vid,name='Системный аналитик'):return {'id':str(vid),'name':name,'company':'СБЕР','employer_id':'3529','description':''}
class ResumeIdentityTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);m.STATE_PATH=Path(self.temp.name)/'progress.json';m.PROGRESS={'actions':{},'completed_interviews':{}};m.CUR_VACANCY.clear();m.PINNED_VACANCY=None;m._history.clear();self.status=patch.object(m,'run_status');self.status.start();self.addCleanup(self.status.stop)
  self.resume={'peer_id':m.TARGET_PEER,'dir':'in','mid':'819','text':'Давайте продолжим общение по вакансии Системный аналитик. Мы остановились на этом месте:\nОстались ли у Вас какие-либо вопросы ко мне?','buttons':[]}
 def select(self,age=10,status='confirmed'):
  scope={**item(2),'selection':{'menu_fingerprint':m.TARGET_PEER+':818:abc','selected_at':time.time()-age,'label':'4. Системный аналитик','proof':'official_id'}}
  m.PROGRESS['pending_selection']=scope;m.PROGRESS['current']=m.current_scope_record(scope);m.CUR_VACANCY.update(m.PROGRESS['current']);m.PROGRESS['actions'][m.TARGET_PEER+':818:abc:button-native:4. Системный аналитик']=status
  return scope
 async def test_resume_header_extracts_generic_title_and_not_question(self):self.assertEqual(c.intro_identity(self.resume['text']),'Системный аналитик')
 async def test_resume_header_preserves_parentheses_and_inner_period(self):
  self.assertEqual(c.intro_identity('Давайте продолжим общение по вакансии Системный аналитик (Р7. Офис). Мы остановились на этом месте:\nВопрос'),'Системный аналитик (Р7. Офис)')
 async def test_old_full_intro_still_works(self):self.assertEqual(c.intro_identity('Получил Ваш отклик на позицию Системный аналитик.'),'Системный аналитик')
 async def test_recent_verified_selection_binds_resume_without_full_intro(self):
  self.select()
  with patch.object(m,'get_catalog',return_value={'items':[item(1),item(2)]}):await m.establish_interview(self.resume)
  self.assertEqual(m.CUR_VACANCY['vacancy_id'],'2');self.assertEqual(m.CUR_VACANCY['intro_mid'],'819');self.assertNotIn('pending_selection',m.PROGRESS)
 async def test_confirmed_selection_survives_restart_after_five_minutes(self):
  self.select(age=3600);m.PROGRESS['active_context']={'key':'hh:2','messages':[{'role':'assistant','content':'Ранее описал API и Kafka'}]}
  with patch.object(m,'get_catalog',return_value={'items':[item(1),item(2)]}):await m.establish_interview(self.resume)
  self.assertEqual(m.PINNED_VACANCY['id'],'2');self.assertEqual(m._history[0]['content'],'Ранее описал API и Kafka')
 async def test_confirmed_new_identity_proofs_survive_restart(self):
  for proof in ('summary_unique_description','verified_entry_identity'):
   with self.subTest(proof=proof):
    scope=self.select(age=3600);scope['selection']['proof']=proof
    self.assertTrue(m.pending_selection_matches(self.resume,scope))
 async def test_confirmed_menu_title_alias_binds_same_hh_id(self):
  scope=self.select(age=3600)
  scope['name']='Бизнес-аналитик (финансовые модели корпоративных клиентов)'
  alias='Бизнес-аналитик / Дата-аналитик (финансовые модели корпоративных клиентов)'
  scope['selection'].update(title=alias,label='4. '+alias)
  m.PROGRESS['actions'][m.TARGET_PEER+':818:abc:button-native:4. '+alias]='confirmed'
  message={**self.resume,'text':'Давайте продолжим общение по вакансии '+alias+'. Мы остановились на этом месте:\nРасскажите о своём опыте.'}
  with patch.object(m,'get_catalog',return_value={'items':[item(1),item(2,scope['name'])]}):await m.establish_interview(message)
  self.assertEqual(m.CUR_VACANCY['vacancy_id'],'2');self.assertNotIn('pending_selection',m.PROGRESS)
 async def test_alias_without_confirmed_or_recent_selection_is_not_trusted(self):
  scope=self.select(age=3600,status='attempting');scope['selection']['title']='Другое название'
  message={**self.resume,'text':'Получил Ваш отклик на позицию Другое название.'}
  with patch.object(m,'get_catalog',return_value={'items':[item(1),item(2)]}):
   with self.assertRaises(NeedsDecision):await m.establish_interview(message)
 async def test_intro_title_cannot_override_confirmed_hh_id(self):
  self.select();message={**self.resume,'text':'Получил Ваш отклик на позицию Другой аналитик.'}
  with patch.object(m,'get_catalog',return_value={'items':[item(2),item(3,'Другой аналитик')]}):await m.establish_interview(message)
  self.assertEqual(m.CUR_VACANCY['vacancy_id'],'2')
 async def test_recent_unconfirmed_click_cannot_bind_renamed_intro(self):
  scope=self.select(age=1,status='attempting');scope['selection']['title']='Другое название'
  message={**self.resume,'text':'Получил Ваш отклик на позицию Другое название.'}
  self.assertFalse(m.pending_selection_matches(message,scope))
  with patch.object(m,'get_catalog',return_value={'items':[item(1),item(2)]}):
   with self.assertRaises(NeedsDecision):await m.establish_interview(message)
 async def test_manual_change_command_invalidates_pending_selection(self):
  self.select();command={**self.resume,'mid':'819','dir':'out','text':'/change_vacancy'}
  with self.assertRaises(NeedsDecision):m.visible_interview_intros([command,{**self.resume,'mid':'820'}])
 async def test_manual_change_then_fresh_menu_can_be_processed(self):
  self.select();command={**self.resume,'mid':'819','dir':'out','text':'/change_vacancy'}
  menu={**self.resume,'mid':'820','text':'По какой из них продолжить диалог?','buttons':['1. Аналитик']}
  self.assertEqual(m.visible_interview_intros([command,menu]),[])
 async def test_actual_third_title_preserves_selected_project_id(self):
  scope=self.select();scope['name']='Системный аналитик внедрения (Платформа V Multi Data Clusters)'
  message={**self.resume,'text':'Получил Ваш отклик на позицию Аналитик проекта внедрения (Платформа V Multi Data Clusters).'}
  with patch.object(m,'get_catalog',return_value={'items':[item(2,scope['name'])]}):await m.establish_interview(message)
  self.assertEqual(m.CUR_VACANCY['vacancy_id'],'2')
 async def test_changed_application_invalidates_selected_alias(self):
  scope=self.select();scope['negotiation_id']='old'
  with patch.object(m,'get_catalog',return_value={'items':[{**item(2),'negotiation_id':'new'}]}):
   with self.assertRaises(NeedsDecision):await m.establish_interview(self.resume)
 async def test_expired_unconfirmed_selection_cannot_guess_id(self):
  self.select(age=3600,status='attempting')
  with patch.object(m,'get_catalog',return_value={'items':[item(1),item(2)]}):
   with self.assertRaises(NeedsDecision):await m.establish_interview(self.resume)
 async def test_resume_without_any_selection_stops_for_generic_title(self):
  with patch.object(m,'get_catalog',return_value={'items':[item(1),item(2)]}):
   with self.assertRaises(NeedsDecision):await m.establish_interview(self.resume)
 async def test_old_resume_before_menu_cannot_replace_scope(self):
  self.select();old={**self.resume,'mid':'817'};self.assertEqual(m.visible_interview_intros([old]),[])
 async def test_another_menu_invalidates_old_pending_selection(self):
  self.select();menu={**self.resume,'mid':'820','text':'По какой из них продолжить диалог?','buttons':['1. Аналитик']};new={**self.resume,'mid':'821'}
  with self.assertRaises(NeedsDecision):m.visible_interview_intros([menu,new])
 async def test_foreign_peer_does_not_use_saved_selection(self):
  scope=self.select(age=3600);self.assertFalse(m.pending_selection_matches({**self.resume,'peer_id':'123'},scope))

if __name__=='__main__':unittest.main()
