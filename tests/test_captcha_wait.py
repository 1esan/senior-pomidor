import sys,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
from hh_captcha import install,read_state,valid_url,wait_for_user,CaptchaWaitExpired
from hh_applicant_tool.api.errors import CaptchaRequired
from runtime import save_json

class CaptchaTests(unittest.TestCase):
    def error(self):
        r=Mock(status_code=403);r.request=Mock()
        return CaptchaRequired(r,{'errors':[{'type':'captcha_required','captcha_url':'https://hh.ru/account/captcha?state=test'}]})
    def test_no_retry_until_explicit_resume(self):
        with tempfile.TemporaryDirectory() as d:
            original=Mock(side_effect=[self.error(),{}]);client=Mock(request=original)
            def resume(base,url,job):
                self.assertEqual(original.call_count,1)
            install(client,d,'job')
            with patch('hh_captcha.wait_for_user',side_effect=resume) as wait:
                self.assertEqual(client.request('POST','/negotiations',{'vacancy_id':'1'}),{})
            self.assertEqual(original.call_args_list[0],original.call_args_list[1]);wait.assert_called_once()
    def test_wait_loop_makes_no_api_requests(self):
        with tempfile.TemporaryDirectory() as d:
            ticks=[0]
            def sleep(n):
                ticks[0]+=1
                state=read_state(d);self.assertEqual(state['status'],'waiting')
                save_json(Path(d)/'.state/hh-captcha.json',{**state,'status':'resume_requested'})
            wait_for_user(d,'https://hh.ru/account/captcha?state=test','job',clock=lambda:ticks[0],sleep=sleep,max_wait=10)
            self.assertEqual(read_state(d)['status'],'checking')
    def test_network_failures_are_not_retried(self):
        with tempfile.TemporaryDirectory() as d:
            original=Mock(side_effect=TimeoutError('unknown result'));client=Mock(request=original);install(client,d,'job')
            with self.assertRaises(TimeoutError):client.request('POST','/negotiations',{})
            original.assert_called_once()
    def test_user_can_stop_waiting(self):
        with tempfile.TemporaryDirectory() as d:
            def stop(_):raise KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):wait_for_user(d,'https://hh.ru/account/captcha?state=test','job',sleep=stop)
            self.assertEqual(read_state(d)['status'],'stopped')
    def test_only_official_captcha_links(self):
        for url in ['https://hh.ru.evil.example/account/captcha','http://hh.ru/account/captcha','https://hh.ru/oauth/token']:
            self.assertFalse(valid_url(url))

if __name__=='__main__':unittest.main()
