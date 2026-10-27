import importlib.util
import logging
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch
import requests
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
import model_retry as m
from autonomous_runtime import NeedsDecision

class RetryTests(unittest.TestCase):
 def setUp(self):
  self.clock=1000.
  self.session=Mock();self.report=Mock();self.log=Mock()
  self.config={'model_retry_attempts':3,'model_retry_initial_seconds':5,'model_retry_max_seconds':10}
 def response(self,status=200,error=None,content='Ответ'):
  r=Mock(status_code=status,ok=status<400)
  r.json.return_value={'error':error} if error is not None else {'message':{'content':content}}
  return r
 def sleep(self,seconds):self.clock+=seconds
 def run_generate(self,deadline=None):
  with patch.object(m.time,'time',side_effect=lambda:self.clock),patch.object(m.time,'monotonic',side_effect=lambda:self.clock),patch.object(m.time,'sleep',side_effect=self.sleep):
   return m.generate(self.session,'local',{'messages':[]},timeout=180,config=self.config,deadline=deadline,report=self.report,logger=self.log)
 def test_success_once(self):
  self.session.post.return_value=self.response();self.assertEqual(self.run_generate(),'Ответ');self.assertEqual(self.session.post.call_count,1)
 def test_connection_timeout_then_success(self):
  self.session.post.side_effect=[requests.ConnectionError(),requests.Timeout(),self.response()]
  self.assertEqual(self.run_generate(),'Ответ');self.assertEqual(self.clock,1015);self.assertEqual(self.session.post.call_count,3)
 def test_wrapped_network_502_retried(self):
  self.session.post.side_effect=[self.response(502,{'code':'network_error','retryable':True}),self.response()]
  self.assertEqual(self.run_generate(),'Ответ');self.assertEqual(self.clock,1005)
 def test_server_503_without_json_retried(self):
  bad=self.response(503);bad.json.side_effect=ValueError()
  self.session.post.side_effect=[bad,self.response()];self.assertEqual(self.run_generate(),'Ответ')
 def test_auth_and_limits_never_retried_even_wrapped(self):
  for code,status in [('invalid_grant',401),('subscription_sharing_usage_limit_exceeded',429),('rate_limit_exceeded',429),('luna_not_verified_for_account',409),('chatpass_v2_scope_not_authorized',403)]:
   with self.subTest(code=code):
    self.session.reset_mock();self.session.post.side_effect=None;self.session.post.return_value=self.response(502,{'code':code,'status':status,'retryable':True})
    with self.assertRaises(NeedsDecision):self.run_generate()
    self.assertEqual(self.session.post.call_count,1)
 def test_explicit_nonretryable_502_stops(self):
  self.session.post.return_value=self.response(502,{'code':'adapter_error','retryable':False})
  with self.assertRaises(NeedsDecision):self.run_generate()
  self.assertEqual(self.session.post.call_count,1)
 def test_exhaustion_is_bounded_and_visible(self):
  self.session.post.side_effect=requests.ConnectionError()
  with self.assertRaisesRegex(NeedsDecision,'исчерпаны'):self.run_generate()
  self.assertEqual(self.session.post.call_count,3);self.assertEqual(self.report.call_args.kwargs['phase'],'model_error')
 def test_deadline_prevents_request(self):
  with self.assertRaises(NeedsDecision):self.run_generate(deadline=999)
  self.session.post.assert_not_called()
 def test_deadline_prevents_retry(self):
  self.session.post.side_effect=requests.Timeout()
  with self.assertRaises(NeedsDecision):self.run_generate(deadline=1004)
  self.assertEqual(self.session.post.call_count,1);self.assertEqual(self.session.post.call_args.kwargs['timeout'],4)
 def test_malformed_success_retried(self):
  self.session.post.side_effect=[self.response(content=''),self.response()];self.assertEqual(self.run_generate(),'Ответ')
 def test_raw_chat_uses_same_retry_in_both_modes(self):
  with patch('logging.FileHandler',return_value=logging.NullHandler()):
   spec=importlib.util.spec_from_file_location('retry_giga',BASE/'giga-bot.py');bot=importlib.util.module_from_spec(spec);spec.loader.exec_module(bot)
  for autonomous in [False,True]:
   with self.subTest(autonomous=autonomous),patch.object(bot,'run_status'),patch.object(bot.candidate_rules,'load_profile',return_value={}),patch.object(bot.candidate_rules,'build_system_prompt',return_value='test'),patch.object(m,'generate',return_value='Ответ') as generate:
    bot.AUTONOMOUS=autonomous;bot.WEB_DEADLINE=None
    self.assertEqual(bot._raw_chat('вопрос'),'Ответ');generate.assert_called_once()
 def test_no_secrets_logged(self):
  self.session.post.return_value=self.response(502,{'code':'bad SECRET key','message':'SECRET body','retryable':False})
  with self.assertRaises(NeedsDecision):self.run_generate()
  self.assertNotIn('SECRET',str(self.log.mock_calls)+str(self.report.mock_calls))

if __name__=='__main__':unittest.main()
