import argparse,contextlib,io,json,socket,sys,unittest,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
BASE=Path(__file__).resolve().parents[1] if Path(__file__).parent.name=='tests' else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
import hh,operations
from vacancy_tests import prepare_test,TestNeedsReview
from hh_applicant_tool.operations.apply_vacancies import Operation
PROFILE={'name':'Тестовый владелец','profile_confirmed':True,'resume_text':'Опыт SQL','salary_min':110000}
V={'id':'12','name':'Системный аналитик','description':'API','alternate_url':'https://hh.ru/vacancy/12','employer':{'id':'7','name':'Компания'},'has_test':True}
def task(opened=False,multiple=False):
 return {'id':1,'description':'Вопрос по SQL','open':str(opened).lower(),'multiple':str(multiple).lower(),'candidateSolutions':[] if opened else [{'id':'10','text':'Первый'},{'id':'20','text':'Второй'}]}
def testdata(t=None):return {'uidPk':'u','guid':'g','startTime':'s','required':'true','tasks':[t or task()]}
def answer(ids=None,text='',review=False):return json.dumps({'choice_ids':ids if ids is not None else ['20'],'text':text,'needs_review':review})
class TestValidation(unittest.TestCase):
 def prepare(self,t=None,raw=None):return prepare_test(testdata(t),V,Mock(complete=Mock(return_value=raw or answer())),lambda t:None)
 def test_single(self):self.assertEqual(self.prepare()[0],{'task_1':'20'})
 def test_multi(self):self.assertEqual(self.prepare(task(multiple=True),answer(['10','20']))[0],{'task_1':['10','20']})
 def test_text(self):self.assertEqual(self.prepare(task(opened=True),answer([],text='SQL использую в работе.'))[0],{'task_1_text':'SQL использую в работе.'})
 def test_open_multiple_schema_is_text(self):
  payload,_=self.prepare(task(opened=True,multiple=True),answer([],text='Я бы начал с анализа контрактов.'))
  self.assertEqual(payload,{'task_1_text':'Я бы начал с анализа контрактов.'})
 def test_hypothesis_passes_as_text_and_keeps_its_modality(self):
  text='В Example Employer Alpha я описывал API. Для vLLM я бы определил контракт, таймауты и ограничения нагрузки.'
  payload,_=self.prepare(task(opened=True),answer([],text=text))
  self.assertEqual(payload['task_1_text'],text)
 def test_never_guesses(self):
  for raw in ['20','Выбираю 20','```json\n'+answer()+'\n```',answer(['999']),answer(['10','20']),answer(['20','20']),answer(review=True),answer([20]),answer(text='лишний текст')]:
   with self.subTest(raw=raw),self.assertRaises(TestNeedsReview):self.prepare(raw=raw)
 def test_unknown_flags_and_formats(self):
  for t in [{**task(),'open':'other'},{**task(),'multiple':None},{**task(),'id':'1&task_2'},{**task(),'candidateSolutions':[]},{**task(),'description':''}]:
   with self.subTest(task=t),self.assertRaises(TestNeedsReview):self.prepare(t)
 def test_external_link_no_ai_call(self):
  ai=Mock()
  with self.assertRaises(TestNeedsReview):prepare_test(testdata({**task(),'description':'Перейдите https://example.com'}),V,ai,lambda t:None)
  ai.complete.assert_not_called()
 def test_bad_text_guard(self):
  with self.assertRaises(TestNeedsReview):prepare_test(testdata(task(opened=True)),V,Mock(complete=Mock(return_value=answer([],text='NEEDS_USER'))),lambda t:'нет личного факта')
 def test_review_regenerates_into_grounded_answer(self):
  ai=Mock();ai.complete.side_effect=[answer([],review=True),answer([],text='В Example Employer Alpha я работал системным аналитиком в контуре тестового сервиса операций: описывал API и торговые поручения.')]
  payload,_=prepare_test(testdata(task(opened=True)),V,ai,lambda t:None)
  self.assertIn('Example Employer Alpha',payload['task_1_text']);self.assertEqual(ai.complete.call_count,2)
  self.assertIn('Переформулируй',ai.complete.call_args.args[0])
 def test_service_phrase_is_regenerated_not_sent(self):
  ai=Mock();ai.complete.side_effect=[answer([],text='В резюме не указано, уточню.'),answer([],text='Я описывал API и статусные модели в Example Employer Alpha.')]
  payload,_=prepare_test(testdata(task(opened=True)),V,ai,lambda t:'Служебная фраза' if 'уточню' in t else None)
  self.assertNotIn('уточню',payload['task_1_text']);self.assertEqual(ai.complete.call_count,2)
 def test_persistent_unknown_stays_manual_after_three_attempts(self):
  ai=Mock();ai.complete.return_value=answer([],review=True)
  with self.assertRaises(TestNeedsReview):prepare_test(testdata(task(opened=True)),V,ai,lambda t:None)
  self.assertEqual(ai.complete.call_count,3)
 def test_memory_only_within_questionnaire(self):
  data=testdata(task(opened=True));data['tasks'].append({**task(opened=True),'id':2})
  ai=Mock();ai.complete.return_value=answer([],text='Работал с API.')
  prepare_test(data,V,ai,lambda t:None)
  second=ai.complete.call_args_list[1].args[0]
  self.assertIn('Работал с API.',second)
  ai.reset_mock();prepare_test(testdata(task(opened=True)),V,ai,lambda t:None)
  self.assertIn('"previous_answers_this_test": []',ai.complete.call_args.args[0])
 def test_duplicate_task_ids(self):
  data=testdata();data['tasks']*=2
  with self.assertRaises(TestNeedsReview):prepare_test(data,V,Mock(complete=Mock(return_value=answer())),lambda t:None)

class RealSchemaTests(unittest.TestCase):
 def test_synthetic_forms_parse(self):
  fixture=BASE/'tests/fixtures/hh_test_question_schemas.json'
  for vid,tasks in json.loads(fixture.read_text()).items():
   with self.subTest(vacancy=vid):
    def generate(prompt):
     context=json.loads(prompt.split('\n',1)[1])
     if context['type']=='text':return answer([],text='Я бы начал с анализа требований и интеграций.')
     return answer([next(iter(context['options']))])
    payload,review=prepare_test({**testdata(),'tasks':tasks},V,Mock(complete=generate),lambda t:None)
    self.assertEqual(len(payload),len(tasks));self.assertEqual(len(review),len(tasks))

class ExperienceSourceTests(unittest.TestCase):
 def test_source_is_read_fresh_and_frontmatter_removed(self):
  import vacancy_tests as vt
  with tempfile.TemporaryDirectory() as d,patch.object(vt,'BASE',Path(d)):
   path=Path(d)/'case_notes.md';path.write_text('---\nstatus: archive\n---\nПример Example Employer Alpha: корреляция тестовых операций.')
   (Path(d)/'test_sources.json').write_text(json.dumps({'experience_files':[str(path)]}))
   first=vt.test_system_prompt(PROFILE)
   self.assertIn('корреляция тестовых операций',first);self.assertNotIn('status: archive',first)
   self.assertIn('имеют приоритет',first)
   path.write_text('Пример Example Marketplace Beta: запаздывающие тестовые события.')
   second=vt.test_system_prompt(PROFILE)
   self.assertIn('запаздывающие тестовые события',second);self.assertNotIn('корреляция тестовых операций',second)
 def test_missing_config_keeps_profile_only(self):
  import vacancy_tests as vt
  with tempfile.TemporaryDirectory() as d,patch.object(vt,'BASE',Path(d)):
   self.assertEqual(vt.load_experience_context(),'')
 def test_broken_configured_source_requires_review(self):
  import vacancy_tests as vt
  with tempfile.TemporaryDirectory() as d,patch.object(vt,'BASE',Path(d)):
   (Path(d)/'test_sources.json').write_text(json.dumps({'experience_files':[str(Path(d)/'missing.md')]}))
   with self.assertRaises(TestNeedsReview):vt.load_experience_context()

class FlowTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  import common
  self.base_patch=patch.object(common,'BASE',Path(self.temp.name));self.base_patch.start();self.addCleanup(self.base_patch.stop)
  for source in ('vacancy_tests.py','candidate.py','screening_facts.py'):(Path(self.temp.name)/source).write_bytes((BASE/source).read_bytes())
  self.op=Operation();self.tool=Mock();self.op.tool=self.tool;self.op.dry_run=True;self.op.cover_letter_ai=Mock()
  self.policy_patch=patch('vacancy_policy.application_decision',return_value=('allow','OK'));self.policy_patch.start();self.addCleanup(self.policy_patch.stop)
  self.tool.xsrf_token='offline-xsrf'
  self.tool.get_openai_args.return_value={'api_key':'offline','base_url':'http://localhost'}
  self.tool.get_ai_client.return_value.complete.return_value=answer()
  self.tool.employer_contact_guard.return_value=V
  self.tool.candidate_vacancy_policy.return_value=('allow','OK')
  self.op._get_vacancy_tests=Mock(return_value={'12':testdata()})
  self.profile_patch=patch('candidate.load_profile',return_value=PROFILE);self.profile_patch.start();self.addCleanup(self.profile_patch.stop)
  self.reply_patch=patch('candidate.reply_problem',return_value=None);self.reply_patch.start();self.addCleanup(self.reply_patch.stop)
  self.tool.session.post.side_effect=AssertionError('No real send')
 def solve(self):
  with contextlib.redirect_stdout(io.StringIO()):return self.op._solve_vacancy_test('12','resume','Письмо',V)
 def test_preview_never_posts_or_creates_intent(self):
  self.assertTrue(self.solve()['success']);self.tool.session.post.assert_not_called();self.tool.application_intent.assert_not_called()
  prompt=self.tool.get_ai_client.call_args.kwargs['system_prompt']
  self.assertIn('Тестовый владелец',prompt);self.assertIn('Это первичный скрининг',prompt);self.assertIn('живым деловым',prompt);self.assertIn('я бы начал с',prompt);self.assertIn('не отвечай ложным',prompt)
 def test_fresh_policy_blocks_before_intent(self):
  self.tool.candidate_vacancy_policy.return_value=('skip','Младший')
  with self.assertRaises(TestNeedsReview):self.solve()
  self.tool.application_intent.assert_not_called();self.tool.session.post.assert_not_called()
 def test_guard_blocks(self):
  self.tool.employer_contact_guard.side_effect=RuntimeError('Компания запрещена')
  with self.assertRaises(RuntimeError):self.solve()
  self.tool.session.post.assert_not_called()
 def test_live_order_and_payload(self):
  self.op.dry_run=False;events=[]
  self.tool.application_intent.side_effect=lambda *a:events.append('intent')
  response=Mock(is_redirect=False,status_code=200,headers={});response.json.return_value={'success':'true'}
  self.tool.session.post.side_effect=lambda *a,**kw:(events.append('post') or response)
  self.assertEqual(self.solve()['success'],'true');self.assertEqual(events,['intent','post'])
  kwargs=self.tool.session.post.call_args.kwargs
  self.assertEqual(kwargs['data']['task_1'],'20');self.assertEqual(kwargs['timeout'],(10,45));self.assertFalse(kwargs['allow_redirects'])
 def test_related_case_letter_matches_intent_payload_and_return(self):
  case='Есть схожий опыт: в Example Employer Alpha описывал проверки и ограничения API для финансовых операций.'
  self.tool.get_ai_client.return_value.complete.return_value=json.dumps({'choice_ids':['20'],'text':'','needs_review':False,'related_case':case},ensure_ascii=False)
  self.op.dry_run=False;response=Mock(status_code=200,headers={});response.json.return_value={'success':True};self.tool.session.post.side_effect=None;self.tool.session.post.return_value=response
  result=self.solve();sent=self.tool.session.post.call_args.kwargs['data']
  self.assertIn(case,sent['letter']);self.assertEqual(result['letter'],sent['letter'])
  self.assertEqual(self.tool.application_intent.call_args.args[1]['message'],sent['letter'])
  self.assertNotIn('related_case',sent)
 def test_unknown_delivery_not_retried(self):
  self.op.dry_run=False;self.tool.session.post.side_effect=TimeoutError('timeout')
  with self.assertRaises(TimeoutError):self.solve()
  self.assertEqual(self.tool.session.post.call_count,1);self.tool.application_intent.assert_called_once()
  self.assertEqual(self.tool.vacancy_test_report.call_args.args[1],'unconfirmed')
 def test_missing_intent_blocks_live(self):
  self.op.dry_run=False;self.tool.application_intent=None
  with self.assertRaises(TestNeedsReview):self.solve()
  self.tool.session.post.assert_not_called()
 def test_invalid_answer_no_intent(self):
  self.tool.get_ai_client.return_value.complete.return_value=answer(['999'])
  with self.assertRaises(TestNeedsReview):self.solve()
  self.tool.application_intent.assert_not_called()
 def test_no_ai_blocks(self):
  self.op.cover_letter_ai=None
  with self.assertRaises(TestNeedsReview):self.solve()
 def test_negative_result_not_success(self):
  self.op.dry_run=False;response=Mock(is_redirect=False,status_code=200,headers={});response.json.return_value={'error':'bad'};self.tool.session.post.side_effect=None;self.tool.session.post.return_value=response
  with self.assertRaises(RuntimeError):self.solve()
 def test_pipeline_counts_test_preview_and_live_once(self):
  for live,use_hook in ((False,False),(True,False),(False,True),(True,True)):
   with self.subTest(live=live,use_hook=use_hook):
    op=Operation();command=hh.build_command(hh.parser().parse_args(['apply','--query','Example Analyst','--solve-tests']+(['--live'] if live else [])),PROFILE)
    parser=argparse.ArgumentParser();op.setup_parser(parser);args=parser.parse_args(command[command.index('apply')+1:]);args.use_ai=True
    tool=Mock();tool.config={};tool.application_budget_exhausted=lambda:False;tool.candidate_cover_letter=None
    tool.get_openai_args.return_value={'api_key':'offline','base_url':'http://localhost'}
    ai=Mock();ai.complete.return_value='Готов обсудить интеграции.';tool.get_ai_client.return_value=ai
    if use_hook:tool.candidate_cover_letter=Mock(return_value=ai.complete.return_value)
    with patch.object(op,'_apply_vacancies'):op.run(tool,args)
    tool.api_client.get.return_value=V;tool.candidate_vacancy_policy.return_value=('allow','OK');tool.employer_contact_guard.return_value=V
    op._get_vacancies=Mock(return_value=iter([V]));op._solve_vacancy_test=Mock(return_value={'success':True})
    with contextlib.redirect_stdout(io.StringIO()):op._apply_resume({'id':'r','title':'СА','alternate_url':'offline'},{},set())
    op._solve_vacancy_test.assert_called_once();tool.application_result.assert_called_once_with(V,ai.complete.return_value,op.dry_run)
    if use_hook:tool.candidate_cover_letter.assert_called_once_with(V)
    tool.api_client.post.assert_not_called()
 def test_panel_flag_propagates_and_defaults_skip(self):
  for enabled in (False,True):
   cmd,_=operations.command_for('apply',{'solve_tests':enabled,'queries':'Example Analyst'});args=hh.parser().parse_args(cmd[1:]);self.assertEqual(args.solve_tests,enabled)
   built=hh.build_command(args,PROFILE);self.assertIn('--no-skip-tests' if enabled else '--skip-tests',built)

if __name__=='__main__':
 with patch.object(socket.socket,'connect',side_effect=AssertionError('Network forbidden')):unittest.main(verbosity=2)
