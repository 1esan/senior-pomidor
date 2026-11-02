import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import requests
import common
import hh
from hh_search_state import VacancyRunClaims
from hh_test_transport import classify_test_form, TestSubmissionBlocked
from hh_applicant_tool.operations.apply_vacancies import Operation


def response(url='https://hh.ru/applicant/vacancy_response', status=200, body=None):
    r=requests.Response();r.status_code=status;r.url=url
    r.headers['Content-Type']='application/json' if body is not None else 'text/html'
    r._content=json.dumps(body).encode() if body is not None else b'<html></html>'
    return r


class TestFormLoading(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.patch=patch.object(common,'BASE',Path(self.tmp.name));self.patch.start()
        self.op=Operation();self.op.tool=Mock()
        self.op.tool.parse_initial_state.return_value={'vacancyTests':{'12':{'tasks':[]}}}
        self.url='https://hh.ru/applicant/vacancy_response?vacancyId=12'
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def test_followed_login_redirect_200_stops_before_parsing_or_sending(self):
        self.op.tool.session.get.return_value=response('https://hh.ru/account/login?backurl=private')
        with self.assertRaisesRegex(TestSubmissionBlocked,'Сессия сайта HH истекла'):
            self.op._get_vacancy_tests(self.url)
        self.op.tool.parse_initial_state.assert_not_called();self.op.tool.session.post.assert_not_called()
        data=json.loads(next((Path(self.tmp.name)/'.state/test-http-diagnostics').glob('*')).read_text())
        self.assertEqual(data['kind'],'login');self.assertNotIn('private',json.dumps(data))
    def test_login_initial_state_at_200_is_not_missing_test(self):
        self.op.tool.session.get.return_value=response()
        self.op.tool.parse_initial_state.return_value={'loginForm':{'secret':'private'}}
        with self.assertRaisesRegex(TestSubmissionBlocked,'Сессия сайта HH истекла'):self.op._get_vacancy_tests(self.url)
        self.op.tool.session.post.assert_not_called()
    def test_valid_form_preserved(self):
        self.op.tool.session.get.return_value=response()
        self.assertEqual(self.op._get_vacancy_tests(self.url),{'12':{'tasks':[]}})
        self.op.tool.session.get.assert_called_once()
    def test_captcha_final_page_200_uses_manual_gate_then_reads_once_more(self):
        self.op.tool.session.get.side_effect=[response('https://hh.ru/account/captcha?state=private'),response()]
        with patch.dict('os.environ',{'BOT_JOB_ID':'synthetic'}),patch('hh_captcha.wait_for_user') as wait:
            self.assertIn('12',self.op._get_vacancy_tests(self.url))
        wait.assert_called_once();self.assertEqual(self.op.tool.session.get.call_count,2);self.op.tool.session.post.assert_not_called()
    def test_json_captcha_at_200_also_uses_manual_gate(self):
        self.op.tool.session.get.side_effect=[response(body={'hhcaptcha':{'captchaState':'private'}}),response()]
        with patch.dict('os.environ',{'BOT_JOB_ID':'synthetic'}),patch('hh_captcha.wait_for_user') as wait:
            self.assertIn('12',self.op._get_vacancy_tests(self.url))
        wait.assert_called_once()
    def test_missing_or_malformed_form_stops_mass_skips(self):
        for value in [{}, {'vacancyTests':None}, {'vacancyTests':{}}]:
            self.op.tool.session.get.return_value=response();self.op.tool.parse_initial_state.return_value=value
            with self.subTest(value=value),self.assertRaises(TestSubmissionBlocked):self.op._get_vacancy_tests(self.url)
        self.op.tool.parse_initial_state.side_effect=ValueError('private response')
        with self.assertRaises(TestSubmissionBlocked) as exc:self.op._get_vacancy_tests(self.url)
        self.assertNotIn('private response',str(exc.exception))
    def test_http_error_does_not_generate_or_send(self):
        self.op.tool.session.get.return_value=response(status=403,body={'error':'forbidden'})
        with self.assertRaises(TestSubmissionBlocked):self.op._get_vacancy_tests(self.url)
        self.op.tool.parse_initial_state.assert_not_called();self.op.tool.session.post.assert_not_called()
    def test_wrapper_preserves_sent_results_on_controlled_stop(self):
        def interrupted(fn,*args):raise TestSubmissionBlocked('Сессия сайта HH истекла')
        with tempfile.TemporaryDirectory() as tmp,patch.object(hh,'BASE',Path(tmp)),patch.object(hh,'load_profile',return_value={'profile_confirmed':True}),patch.object(hh,'repeat_pass',side_effect=interrupted),patch.object(hh,'operation_lock',return_value=contextlib.nullcontext()):
            self.assertEqual(hh.run(hh.parser().parse_args(['apply','--query','Example Analyst'])),20)
            ledger=json.loads(next((Path(tmp)/'.state/runs').glob('*')).read_text())
            self.assertEqual(ledger['status'],'needs_attention');self.assertIn('истекла',ledger['message'])


class TestSearchClaims(unittest.TestCase):
    def test_same_id_claimed_once_with_fresh_scope_next_run(self):
        claims=VacancyRunClaims()
        self.assertTrue(claims.claim({'id':12}));self.assertFalse(claims.claim({'id':'12'}))
        self.assertTrue(claims.claim({'id':'13'}));self.assertTrue(VacancyRunClaims().claim({'id':'12'}))
    def test_claim_does_not_change_input(self):
        v={'id':'12','has_test':True};before=dict(v);VacancyRunClaims().claim(v);self.assertEqual(v,before)
    def test_generator_deduplicates_before_full_fetch_or_test_across_queries(self):
        claims=VacancyRunClaims();api=Mock()
        tool=SimpleNamespace(api_client=api,candidate_claim_vacancy=claims.claim)
        op=Operation();op.tool=tool;op.total_pages=2;op.text='first';op._get_search_params=Mock(return_value={})
        api.get.side_effect=[{'items':[{'id':'1'},{'id':'2'}],'pages':2,'found':4},{'items':[{'id':'2'},{'id':'3'}],'pages':2,'found':4},{'items':[{'id':'1'},{'id':'4'}],'pages':1,'found':2}]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            first=list(op._get_vacancies('resume'));op.text='second';second=list(op._get_vacancies('resume'))
        self.assertEqual([v['id'] for v in first],['1','2','3']);self.assertEqual([v['id'] for v in second],['4'])
        self.assertEqual(api.get.call_count,3);self.assertIn('повторов=1',out.getvalue())

if __name__=='__main__':unittest.main()
