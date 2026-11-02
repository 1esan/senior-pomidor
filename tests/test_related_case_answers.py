import unittest,json,tempfile
from pathlib import Path
from unittest.mock import Mock,patch
import requests
from vacancy_tests import prepare_test,TestNeedsReview,attach_related_cases
from hh_test_transport import submit_test
P={'screening_answers':'Example BI Tool не использовал.','resume_text':'Example Employer Alpha: описывал бизнес-валидации API, проверки и защиту от повторного исполнения операций.'}
CASE='Есть схожий опыт: в Example Employer Alpha описывал проверки API и ограничения, чтобы операция не исполнялась повторно.'
def raw(ids=None,text='',case=None):
 d={'choice_ids':ids or [],'text':text,'needs_review':False}
 if case is not None:d['related_case']=case
 return json.dumps(d,ensure_ascii=False)
def task(opened=True,question='Есть ли опыт работы в области информационной безопасности?'):
 return {'id':1,'description':question,'open':str(opened).lower(),'multiple':'false','candidateSolutions':[{'id':'10','text':'Да'},{'id':'20','text':'Нет'}]}
def form(t):return {'uidPk':'u','guid':'g','startTime':'s','required':'true','tasks':[t]}
class RelatedCaseTests(unittest.TestCase):
 def test_mixed_no_retried_into_related_case(self):
  ai=Mock();ai.complete.side_effect=[raw(['20']),raw(text=CASE)]
  payload,review=prepare_test(form(task()),{},ai,lambda text:None,profile=P)
  self.assertEqual(payload,{'task_1':'open','task_1_text':CASE});self.assertEqual(ai.complete.call_count,2)
 def test_closed_choice_keeps_case_out_of_form_fields(self):
  ai=Mock();ai.complete.return_value=raw(['10'],case=CASE)
  payload,review=prepare_test(form(task(False)),{},ai,lambda text:None,profile=P)
  self.assertEqual(payload,{'task_1':'10'});self.assertEqual(review[0]['related_case'],CASE)
 def test_closed_positive_without_case_is_regenerated(self):
  ai=Mock();ai.complete.side_effect=[raw(['10']),raw(['10'],case=CASE)]
  _,review=prepare_test(form(task(False)),{},ai,lambda text:None,profile=P)
  self.assertEqual(ai.complete.call_count,2);self.assertIn('related_case',review[0])
 def test_unknown_no_never_forced_into_yes(self):
  ai=Mock();ai.complete.return_value=raw(['20'])
  with self.assertRaises(TestNeedsReview):prepare_test(form(task(False)),{},ai,lambda text:None,profile=P)
 def test_reframed_closed_answer_always_carries_its_reason_into_letter(self):
  case='В Example Employer Alpha согласовывал правила обработки операций с продуктовой командой и архитектором.'
  ai=Mock();ai.complete.side_effect=[raw(['20']),raw(['10'],case=case)]
  _,review=prepare_test(form(task(False)),{},ai,lambda text:None,profile=P)
  self.assertTrue(review[0]['reframed_from_negative'])
  self.assertIn(case,attach_related_cases('Короткий сопровод.',review))
 def test_known_negative_fact_is_preserved(self):
  ai=Mock();ai.complete.return_value=raw(['20'])
  payload,_=prepare_test(form(task(False,'Есть ли опыт работы с Example BI Tool?')),{},ai,lambda text:None,profile=P)
  self.assertEqual(payload['task_1'],'20')
 def test_office_refusal_is_unchanged(self):
  ai=Mock();ai.complete.return_value=raw(['20'])
  payload,_=prepare_test(form(task(False,'Готовы к работе в офисе в Городе-Образце?')),{},ai,lambda text:None,profile=P)
  self.assertEqual(payload['task_1'],'20')
 def test_service_phrase_cannot_hide_in_case(self):
  ai=Mock();ai.complete.return_value=raw(['10'],case='В резюме не указано, нужно уточнить.')
  with self.assertRaises(TestNeedsReview):prepare_test(form(task(False)),{},ai,lambda text:'bad' if 'резюме' in text else None,profile=P)
 def test_cases_inserted_before_contacts_and_deduplicated(self):
  letter='Доброго времени суток)\n\nТекст.\n\nНадеюсь, можем быть полезны друг другу. Контакты.'
  result=attach_related_cases(letter,[{'related_case':CASE},{'related_case':CASE}])
  self.assertEqual(result.count(CASE),1);self.assertLess(result.index(CASE),result.index('Надеюсь'))
 def test_direct_case_is_recorded_but_does_not_expand_letter(self):
  letter='Короткий сопровод.'
  self.assertEqual(attach_related_cases(letter,[{'related_case':'В Example Employer Alpha проектировал REST API подключения стратегии.'}]),letter)
 def test_got_response_after_network_loss_never_reposts(self):
  tool=Mock(xsrf_token='safe');tool.session.post.side_effect=requests.Timeout();tool.api_client.get.return_value={'relations':['got_response']}
  with tempfile.TemporaryDirectory() as d:result=submit_test(tool,{'id':'1'},{},'https://hh.ru/applicant/vacancy_response',base=d,refresh=Mock(),guard=Mock())
  self.assertTrue(result['reconciled']);tool.session.post.assert_called_once()
 def test_got_response_after_captcha_never_reposts(self):
  tool=Mock(xsrf_token='safe');response=Mock(status_code=403,headers={});response.json.return_value={'hhcaptcha':{'captchaState':'state'}};tool.session.post.return_value=response;tool.api_client.get.return_value={'relations':['got_response']};refresh=Mock()
  with tempfile.TemporaryDirectory() as d,patch.dict('os.environ',{'BOT_JOB_ID':'test'}),patch('hh_captcha.wait_for_user'):
   result=submit_test(tool,{'id':'1'},{},'https://hh.ru/applicant/vacancy_response',base=d,refresh=refresh,guard=Mock())
  self.assertTrue(result['reconciled']);tool.session.post.assert_called_once();refresh.assert_not_called()
if __name__=='__main__':unittest.main()
