import contextlib,io,json,os,socket,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import requests
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model_availability import wait_for_generation,ModelUnavailable
from hh_test_transport import submit_test,TestSubmissionBlocked,classify
from experience_context import TestCheckpoint,select_excerpts
from vacancy_tests import prepare_test,test_system_prompt
from candidate import reply_problem

TEST_PROFILE={'name':'Example Candidate','phone':'TEST-PHONE-000','salary_min':110000,
              'salary_max':130000,'resume_text':'Synthetic profile for isolated tests.'}

def resp(status=200,body=None,headers=None):
 r=Mock(status_code=status,headers=headers or {});r.json.return_value=body if body is not None else {'success':True};return r

def task(tid):return {'id':tid,'description':'Расскажите про API','open':'true','multiple':'true','candidateSolutions':[]}
def result(text):return json.dumps({'choice_ids':[],'text':text,'needs_review':False})

class AvailabilityTests(unittest.TestCase):
 def setUp(self):self.t=0;self.events=[];self.env=patch.dict(os.environ,{'BOT_JOB_ID':''});self.env.start();self.addCleanup(self.env.stop)
 def sleep(self,n):self.t+=n
 def generate(self,request,limit=20):
  return wait_for_generation(request,max_wait=limit,clock=lambda:self.t,sleep=self.sleep,report=self.events.append)
 def test_retry_same_generation_then_success(self):
  ok=resp();call=Mock(side_effect=[resp(502,{'error':{'code':'network_error','retryable':True}}),ok])
  self.assertIs(self.generate(call),ok);self.assertEqual(call.call_count,2);self.assertEqual(self.t,5)
  self.assertEqual([x['status'] for x in self.events],['waiting','resolved'])
 def test_connection_error_retry(self):
  call=Mock(side_effect=[requests.ConnectionError(),resp()]);self.generate(call);self.assertEqual(call.call_count,2)
 def test_auth_and_limit_never_retry(self):
  for code,status in [('invalid_grant',401),('subscription_sharing_usage_limit_exceeded',429),('input_too_large',400)]:
   with self.subTest(code=code):
    call=Mock(return_value=resp(502,{'error':{'code':code,'status':status,'retryable':True if status!=400 else False}}))
    with self.assertRaises(ModelUnavailable):self.generate(call)
    call.assert_called_once()
 def test_wait_exhaustion_is_controlled(self):
  call=Mock(side_effect=requests.Timeout())
  with self.assertRaises(ModelUnavailable):self.generate(call,7)
  self.assertLessEqual(call.call_count,4);self.assertEqual(self.events[-1]['status'],'needs_attention')
 def test_api_client_preserves_reason_and_never_skips_transient_itself(self):
  from hh_applicant_tool.ai.openai import ChatOpenAI
  ai=ChatOpenAI(api_key='offline',base_url='http://localhost',model='gpt-6-luna')
  good=resp(200,{'choices':[{'message':{'content':'Ответ'}}]})
  with patch.object(ai,'_request',return_value=good):self.assertEqual(ai.complete('Вопрос'),'Ответ')
 def test_oversize_fails_before_network(self):
  from hh_applicant_tool.ai.openai import ChatOpenAI
  ai=ChatOpenAI(api_key='offline',base_url='http://localhost',model='gpt-6-luna')
  with patch.object(ai,'_request') as request:
   with self.assertRaisesRegex(ModelUnavailable,'Контекст'):ai.complete('x'*61000)
   request.assert_not_called()

class TransportTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
  self.tool=Mock(xsrf_token='private-xsrf');self.v={'id':'12'};self.payload={'_xsrf':'private-xsrf','task_1_text':'Персональный ответ'}
  self.guard=Mock();self.refresh=Mock(side_effect=lambda p:{**p,'startTime':'new'});self.env=patch.dict(os.environ,{'BOT_JOB_ID':'unit-job'});self.env.start();self.addCleanup(self.env.stop)
 def send(self):return submit_test(self.tool,self.v,self.payload,'https://hh.ru/applicant/vacancy_response?vacancyId=12',base=self.base,refresh=self.refresh,guard=self.guard)
 def test_standard_headers_and_success(self):
  self.tool.session.post.return_value=resp();self.send()
  kw=self.tool.session.post.call_args.kwargs;self.assertEqual(kw['headers']['Origin'],'https://hh.ru');self.assertEqual(kw['headers']['Accept'],'application/json');self.assertFalse(kw['allow_redirects'])
 def test_plain_403_stops_and_preserves_diagnostic_without_secrets(self):
  self.tool.session.post.return_value=resp(403,{'error':'forbidden','token':'private-token'})
  with self.assertRaisesRegex(TestSubmissionBlocked,'403'):self.send()
  self.tool.session.post.assert_called_once()
  text=next((self.base/'.state/test-http-diagnostics').glob('*.json')).read_text();self.assertNotIn('private',text);self.assertNotIn('Персональный',text);self.assertIn('forbidden',text)
 def test_captcha_even_at_200_waits_before_retry(self):
  self.tool.session.post.side_effect=[resp(200,{'hhcaptcha':{'captchaState':'private-state'}}),resp()]
  self.tool.api_client.get.return_value={'relations':[]}
  def waited(*a):self.assertEqual(self.tool.session.post.call_count,1)
  with patch('hh_captcha.wait_for_user',side_effect=waited) as wait:self.assertTrue(self.send()['success'])
  wait.assert_called_once();self.refresh.assert_called_once();self.assertEqual(self.guard.call_count,2)
 def test_captcha_reconcile_avoids_second_post(self):
  self.tool.session.post.return_value=resp(403,{'hhcaptcha':{'captchaState':'state'}})
  self.tool.api_client.get.return_value={'relations':['already_applied']}
  with patch('hh_captcha.wait_for_user'):self.assertTrue(self.send()['reconciled'])
  self.tool.session.post.assert_called_once();self.refresh.assert_not_called()
 def test_network_unknown_never_retries(self):
  self.tool.session.post.side_effect=requests.Timeout()
  with self.assertRaises(TestSubmissionBlocked):self.send()
  self.tool.session.post.assert_called_once()
 def test_untrusted_captcha_is_not_opened(self):
  self.tool.session.post.return_value=resp(403,{'captcha_url':'https://evil.example/account/captcha'})
  with patch('hh_captcha.wait_for_user') as wait:
   with self.assertRaises(TestSubmissionBlocked):self.send()
  wait.assert_not_called()
 def test_no_xsrf_never_posts(self):
  self.tool.xsrf_token=None
  with self.assertRaises(TestSubmissionBlocked):self.send()
  self.tool.session.post.assert_not_called()
 def test_changed_form_does_not_repost(self):
  self.tool.session.post.return_value=resp(403,{'hhcaptcha':{'captchaState':'state'}});self.tool.api_client.get.return_value={'relations':[]};self.refresh.side_effect=TestSubmissionBlocked('changed')
  with patch('hh_captcha.wait_for_user'),self.assertRaises(TestSubmissionBlocked):self.send()
  self.tool.session.post.assert_called_once()
 def test_csrf_classified(self):self.assertEqual(classify(resp(403,{'errors':[{'type':'invalid_xsrf'}]}))[0],'csrf')

class CheckpointTests(unittest.TestCase):
 def test_resume_after_late_model_failure_uses_earlier_answer(self):
  with tempfile.TemporaryDirectory() as d:
   cp=TestCheckpoint(d,'12','resume','same context');ai=Mock();ai.complete.side_effect=[result('Работал с API.'),ModelUnavailable('offline')]
   data={'uidPk':'u','guid':'g','startTime':'s','required':'true','tasks':[task(1),task(2)]}
   with self.assertRaises(ModelUnavailable):prepare_test(data,{},ai,lambda t:None,cp)
   ai2=Mock();ai2.complete.return_value=result('Я бы проверил контракт.')
   answers,_=prepare_test(data,{},ai2,lambda t:None,TestCheckpoint(d,'12','resume','same context'))
   self.assertEqual(ai2.complete.call_count,1);self.assertEqual(answers['task_1_text'],'Работал с API.')
 def test_context_and_identity_isolate_answers(self):
  with tempfile.TemporaryDirectory() as d:
   cp=TestCheckpoint(d,'12','resume','A');cp.put(task(1),result('API'))
   for vid,context in [('13','A'),('12','B')]:self.assertIsNone(TestCheckpoint(d,vid,'resume',context).get(task(1)))
 def test_source_budget_and_profile_intact(self):
  profile=TEST_PROFILE;prompt=test_system_prompt(profile,'Example API Example Queue Example Employer Alpha')
  self.assertLess(len(prompt),45000);self.assertIn(profile['phone'],prompt);self.assertIn(str(profile['salary_min']//1000),prompt)
 def test_confirmed_labour_and_no_document_offer(self):
  self.assertIsNone(reply_problem('Опыт отражён в трудовой книжке и совпадает с резюме.',TEST_PROFILE))
  for text in ['Готов выслать электронную трудовую книжку.','Пришлю трудовую книжку.']:
   self.assertIsNotNone(reply_problem(text,TEST_PROFILE))

class LoadFormAndJobTests(unittest.TestCase):
 def test_form_403_is_controlled_and_diagnosed(self):
  import common
  from hh_applicant_tool.operations.apply_vacancies import Operation
  with tempfile.TemporaryDirectory() as d,patch.object(common,'BASE',Path(d)):
   op=Operation();op.tool=Mock();op.tool.session.get.return_value=resp(403,{'error':'forbidden'})
   with self.assertRaises(TestSubmissionBlocked):op._get_vacancy_tests('https://hh.ru/applicant/vacancy_response?vacancyId=12')
   op.tool.session.get.assert_called_once();self.assertTrue(list((Path(d)/'.state/test-http-diagnostics').glob('*.json')))
 def test_generation_failure_keeps_run_needs_attention(self):
  import hh
  profile={'name':'Тест','resume_text':'Тестовый профиль системного аналитика','profile_confirmed':True}
  with tempfile.TemporaryDirectory() as d,patch.object(hh,'BASE',Path(d)),patch.object(hh,'load_profile',return_value=profile),patch.object(hh,'repeat_pass',side_effect=ModelUnavailable('network_error')),patch.object(hh,'operation_lock',return_value=contextlib.nullcontext()):
   with contextlib.redirect_stdout(io.StringIO()):code=hh.run(hh.parser().parse_args(['apply','--query','Example Analyst']))
   self.assertEqual(code,20)
   ledger=json.loads(next((Path(d)/'.state/runs').glob('*.json')).read_text());self.assertEqual(ledger['status'],'needs_attention')
 def test_panel_exposes_ai_wait(self):
  import operations
  with tempfile.TemporaryDirectory() as d,patch.object(operations,'BASE',Path(d)):
   f=Path(d)/'.state/ai-wait.json';f.parent.mkdir();f.write_text(json.dumps({'job_id':'unit','status':'waiting','message':'Жду Luna'}))
   job=operations.public({'id':'unit','action':'apply','status':'running'})
   self.assertTrue(job['ai_waiting']);self.assertEqual(job['message'],'Жду Luna')

if __name__=='__main__':
 with patch.object(socket.socket,'connect',side_effect=AssertionError('Network forbidden')):
  unittest.main(verbosity=2)
