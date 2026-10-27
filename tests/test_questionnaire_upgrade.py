import unittest,json,tempfile,contextlib,io,socket
from pathlib import Path
from unittest.mock import Mock,patch
import requests
from vacancy_tests import prepare_test,TestNeedsReview
from screening_facts import known_answer
from hh_test_transport import submit_test,TestSubmissionBlocked
import hh
B=Path(__file__).resolve().parents[1]
FACTS={'screening_answers':'Стаж: 4 года 6 месяцев системным аналитиком.\nСредний балл диплома бакалавра: 4.2 по пятибалльной шкале.\nПубличные выступления: выступал перед аудиторией более 10 человек.\nОформление на последних двух местах работы: официально по ТК РФ в штате.'}
def raw(ids=None,text=''):return json.dumps({'choice_ids':ids or [],'text':text,'needs_review':False})
def task(multi=False):return {'id':1,'description':'Ваш ответ?','open':'true','multiple':str(multi).lower(),'candidateSolutions':[{'id':'10','text':'Да'},{'id':'20','text':'Нет'}]}
def data(t):return {'uidPk':'u','guid':'g','startTime':'s','required':'true','tasks':[t]}
class MixedQuestionsTests(unittest.TestCase):
 def prepare(self,t,r):return prepare_test(data(t),{},Mock(complete=Mock(return_value=r)),lambda text:None)[0]
 def test_mixed_single_custom_has_native_open_marker(self):
  self.assertEqual(self.prepare(task(),raw(text='Работал с API.')),{'task_1':'open','task_1_text':'Работал с API.'})
 def test_mixed_single_choice_does_not_send_custom_text(self):
  self.assertEqual(self.prepare(task(),raw(['10'])),{'task_1':'10'})
 def test_mixed_multi_custom_and_choice(self):
  self.assertEqual(self.prepare(task(True),raw(['10'],text='Работал с API.')),{'task_1':['10','open'],'task_1_text':'Работал с API.'})
 def test_mixed_multi_custom_only(self):
  self.assertEqual(self.prepare(task(True),raw(text='Работал с API.'))['task_1'],['open'])
 def test_invalid_and_contradictory_choices_blocked(self):
  for t,r in [(task(),raw(['10'],text='Ответ')),(task(True),raw(['10','20'])),(task(),raw(['open'])),(task(),raw())]:
   with self.subTest(r=r),self.assertRaises(TestNeedsReview):self.prepare(t,r)
 def test_requested_explanation_retries_bare_yes(self):
  t={**task(),'description':'Есть ли опыт SQL? Если да, то какие запросы писали?'}
  ai=Mock();ai.complete.side_effect=[raw(['10']),raw(text='В БКС сверял операции и историю статусов в SQL.')]
  payload,_=prepare_test(data(t),{},ai,lambda text:None)
  self.assertEqual(payload['task_1'],'open');self.assertEqual(ai.complete.call_count,2)
 def test_real_forms_no_longer_fail_on_open_plus_choices(self):
  forms=json.loads((B/'tests/fixtures/hh_mixed_question_schemas.json').read_text())
  for vid,tasks in forms.items():
   for t in tasks:
    if t['open']!='true' or not t['candidateSolutions']:continue
    with self.subTest(vid=vid,task=t['id']):
     payload=self.prepare(t,raw(text='Я бы начал с требований и проверил контракты.'))
     self.assertIn('open',str(payload['task_'+str(t['id'])]))
class ConfirmedFactsTests(unittest.TestCase):
 def test_grade(self):
  r=json.loads(known_answer('Укажите средний балл диплома бакалавриата',{},True,FACTS));self.assertIn('4.2',r['text'])
 def test_speaking_and_employment_binary(self):
  for q in ['Выступали ли вы перед аудиторией более 10 человек?','На последних двух местах работы вы были трудоустроены официально по ТК в штате?']:
   self.assertEqual(json.loads(known_answer(q,{'1':'Да','2':'Нет'},False,FACTS))['choice_ids'],['1'])
 def test_actual_experience_options_do_not_round_up_to_five(self):
  forms=json.loads((B/'tests/fixtures/hh_mixed_question_schemas.json').read_text());t=forms['138435387'][0]
  opts={x['id']:x['text'] for x in t['candidateSolutions']}
  r=json.loads(known_answer(t['description'],opts,False,FACTS));self.assertEqual(r['choice_ids'],['402702342'])
 def test_profile_facts_skip_generation(self):
  t={**task(),'description':'Укажите средний балл диплома бакалавриата','candidateSolutions':[]}
  ai=Mock();answers,_=prepare_test(data(t),{},ai,lambda text:None,profile=FACTS)
  self.assertIn('4.2',answers['task_1_text']);ai.complete.assert_not_called()
 def test_unknown_and_unrelated_not_invented(self):
  for q in ['Какой был средний балл диплома?','Проводили ли аудиторские проверки?','На каких конференциях выступали?']:
   profile={} if 'балл' in q else FACTS
   self.assertIsNone(known_answer(q,{},True,profile))
class RecoveryTests(unittest.TestCase):
 def test_network_loss_reconciles_without_repeating_post(self):
  tool=Mock(xsrf_token='safe');tool.session.post.side_effect=requests.Timeout();tool.api_client.get.return_value={'relations':['already_applied']}
  with tempfile.TemporaryDirectory() as d:
   result=submit_test(tool,{'id':'1'},{},'https://hh.ru/applicant/vacancy_response',base=d,refresh=Mock(),guard=Mock())
  self.assertTrue(result['reconciled']);tool.session.post.assert_called_once();tool.api_client.get.assert_called_once_with('/vacancies/1')
 def test_unconfirmed_network_loss_keeps_block(self):
  tool=Mock(xsrf_token='safe');tool.session.post.side_effect=requests.Timeout();tool.api_client.get.return_value={'relations':[]}
  with tempfile.TemporaryDirectory() as d,self.assertRaises(TestSubmissionBlocked):submit_test(tool,{'id':'1'},{},'https://hh.ru/applicant/vacancy_response',base=d,refresh=Mock(),guard=Mock())
  tool.session.post.assert_called_once()
 def test_transient_form_get_retried_without_post(self):
  from hh_applicant_tool.operations.apply_vacancies import Operation
  op=Operation();op.tool=Mock();r=Mock(status_code=200,is_redirect=False);op.tool.session.get.side_effect=[requests.Timeout(),r];op.tool.parse_initial_state.return_value={'vacancyTests':{'1':{'tasks':[]}}}
  with patch('time.sleep'):self.assertEqual(op._get_vacancy_tests('https://hh.ru/applicant/vacancy_response'),{'1':{'tasks':[]}})
  self.assertEqual(op.tool.session.get.call_count,2);op.tool.session.post.assert_not_called()
 def test_vendor_preserves_controlled_error_for_wrapper(self):
  from types import SimpleNamespace
  from hh_applicant_tool.tool import HHApplicantTool
  fake=SimpleNamespace(_parser=Mock(),_assign_args=Mock(),create_config_dir=Mock(),setup_logging=Mock(),config_dir_path=Path('/private/tmp'),operation_run=Mock(side_effect=TestSubmissionBlocked('needs attention')),controlled_error_types=(TestSubmissionBlocked,),save_token=Mock(return_value=False),save_cookies=Mock(),_save_config_if_needed=Mock(),_check_system=Mock())
  with self.assertRaises(TestSubmissionBlocked):HHApplicantTool.run(fake,[])
  fake.save_cookies.assert_called_once()
 def test_cancel_is_not_failed_in_run_ledger(self):
  with tempfile.TemporaryDirectory() as d,patch.object(hh,'BASE',Path(d)),patch.object(hh,'load_profile',return_value={'profile_confirmed':True}),patch.object(hh,'repeat_pass',return_value=130),patch.object(hh,'operation_lock',return_value=contextlib.nullcontext()):
   self.assertEqual(hh.run(hh.parser().parse_args(['apply'])),130)
   run=json.loads(next((Path(d)/'.state/runs').glob('*.json')).read_text());self.assertEqual(run['status'],'stopped')
if __name__=='__main__':
 with patch.object(socket.socket,'connect',side_effect=AssertionError('Network forbidden')):unittest.main()
