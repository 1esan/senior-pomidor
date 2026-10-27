import sys,unittest,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from interview_flow import activate_context,complete_context,history_key,next_verified_menu,should_handle_message
from menu_identity import exact_menu_button
from autonomous_runtime import NeedsDecision
class QueueTests(unittest.TestCase):
 def test_old_menu_resumes_in_live_queue_without_autonomous_flag(self):
  self.assertTrue(should_handle_message('menu',{'menu'},first=True,menu=True,auto_next=True,autonomous=False))
 def test_old_question_and_menu_are_not_replayed_each_poll(self):
  self.assertFalse(should_handle_message('question',{'question'},first=True,menu=False,auto_next=True,autonomous=True))
  self.assertFalse(should_handle_message('menu',{'menu'},first=False,menu=True,auto_next=True,autonomous=False))
 def test_same_title_separate_ids_and_resume(self):
  a={'vacancy_id':'1','name':'Системный аналитик','company':'Сбер'};b={**a,'vacancy_id':'2'};state={}
  self.assertEqual(activate_context(state,a),[])
  state['active_context']['messages']=[{'role':'assistant','content':'Кейс только первого интервью'}]
  self.assertEqual(len(activate_context(state,a)),1)
  complete_context(state,a)
  self.assertEqual(state['active_context'],{})
  self.assertEqual(activate_context(state,b),[])
  state['active_context']['messages']=[{'role':'assistant','content':'Второе интервью'}]
  self.assertEqual(activate_context(state,b)[0]['content'],'Второе интервью')
  self.assertEqual(activate_context(state,a),[])
 def test_legacy_history_never_imported(self):
  state={'histories':{'Сбер::СА':[{'role':'assistant','content':'Чужое интервью'}]}}
  self.assertEqual(activate_context(state,{'vacancy_id':'1'}),[])
  self.assertNotIn('histories',state)
 def test_completed_same_title_skipped_other_verified_selected(self):
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);p=base/'.state/giga-menu-identities';p.mkdir(parents=True)
   for vid in ('1','2','3'):(p/(vid+'.json')).write_text(json.dumps({'vacancy_id':vid}))
   calls=[]
   def target(buttons,scope,bubble):
    if scope['id']=='2':raise NeedsDecision('Нет в меню')
    return '1. Системный аналитик'
   def verify(vid):calls.append(vid);return {'id':vid}
   scope,label,skipped=next_verified_menu(base,[],{}, {'completed_interviews':{'hh:1':{}}},verify,target)
   self.assertEqual(scope['id'],'3');self.assertEqual(calls,['3']);self.assertEqual(skipped[0]['vacancy_id'],'2')
 def test_renumbered_menu(self):
  scope={'menu_identity':{'official_url':'https://rabota.sber.ru/search/123','official_id':'123','button_label':'2. Системный аналитик','menu_summary':'Работа с переводами.'}}
  bubble={'text':'Меню\n1. Системный аналитик\nРабота с переводами.','links':['https://rabota.sber.ru/search/123/']}
  self.assertEqual(exact_menu_button(['1. Системный аналитик'],scope,bubble),'1. Системный аналитик')
if __name__=='__main__':unittest.main()
