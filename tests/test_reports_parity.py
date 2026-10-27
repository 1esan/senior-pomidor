import ast,contextlib,io,json,re,runpy,sys,tempfile,unittest,ssl,socket
from pathlib import Path
from unittest.mock import Mock,patch
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
import common

class ReportTests(unittest.TestCase):
    def test_verified_certificates_are_required(self):
        import urllib.request
        with patch('urllib.request.urlopen') as network:
            common.hh_urlopen(urllib.request.Request('https://api.hh.ru/me'))
            ctx=network.call_args.kwargs['context']
            self.assertEqual(ctx.verify_mode,ssl.CERT_REQUIRED)
            self.assertTrue(ctx.check_hostname)
        with self.assertRaises(ValueError):common.hh_urlopen('http://api.hh.ru/me')

    def test_json_reader_uses_only_get_and_relative_hh_paths(self):
        tool=Mock();tool.save_token.return_value=False;tool.api_client.get.return_value={'items':[]}
        with patch.object(common,'_hh_reader',tool):
            self.assertEqual(common.hh_read_json('/negotiations?page=1&per_page=100'),{'items':[]})
            tool.api_client.get.assert_called_once_with('/negotiations',{'page':'1','per_page':'100'})
            tool.api_client.post.assert_not_called()
            with self.assertRaises(ValueError):common.hh_read_json('https://another.example/me')

    def test_full_dashboard_builds_funnel_and_sorts_messages(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);(base/'hh-dash-template.html').write_text((BASE/'hh-dash-template.html').read_text())
            states=['response','discard','discard_by_applicant','interview']
            items=[{'id':str(i),'state':{'id':state},'vacancy':{'name':'Системный аналитик','employer':{'name':'<img src=x onerror=alert(1)>'}},'created_at':'2026-10-13T12:00:00Z','updated_at':'2026-10-13T13:00:00Z'} for i,state in enumerate(states)]
            def api(path):
                if '/messages' in path:return {'pages':1,'items':[{'id':'2','created_at':'2026-10-13T13:00:00Z','author':{'participant_type':'applicant'},'text':'Ответ'}, {'id':'1','created_at':'2026-10-13T12:00:00Z','author':{'participant_type':'employer'},'text':'Вопрос?'}]}
                return {'pages':1,'items':items if 'status=active' in path else []}
            with patch.object(common,'BASE',base),patch.object(common,'HH_CONFIG',base),patch.object(common,'hh_read_json',side_effect=api),patch.object(sys,'argv',['test','--full']),contextlib.redirect_stdout(io.StringIO()):
                m=runpy.run_path(str(BASE/'hh-dash.py'),run_name='__main__')
            text=(base/'hh-dashboard.html').read_text();data=json.loads((base/'statistics.json').read_text())['dashboard']
            self.assertEqual(data['funnel'],{'sent':4,'pending':1,'invited':1,'rejected':1,'other':1})
            self.assertEqual(data['heavy']['un_count'],0)
            self.assertNotIn('<img src=x',text)
            self.assertIn('esc(label)',text)
            self.assertNotIn('качать Сбер на максимум',text)
            self.assertEqual(json.loads((base/'statistics.json').read_text())['dashboard']['funnel']['sent'],4)

    def test_dashboard_can_reuse_complete_analysis_without_network(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);(base/'.state').mkdir()
            (base/'hh-dash-template.html').write_text((BASE/'hh-dash-template.html').read_text())
            at='2026-10-14T14:00:00+00:00'
            row={'id':'1','state':'response','position':'Системный аналитик','employer':'Компания','vacancy_url':'https://hh.ru/vacancy/1','created_at':at,'updated_at':at}
            (base/'hh-data.json').write_text(json.dumps({'complete':True,'generated_at':at,'rows':[row]}))
            (base/'.state/report-messages.json').write_text(json.dumps({'generated_at':at,'messages':{'1':[{'who':'employer','text':'Вопрос?','at':at}]}}))
            with patch.object(common,'BASE',base),patch.object(common,'HH_CONFIG',base),patch.object(common,'hh_read_json',side_effect=AssertionError('Повторный запрос запрещён')),patch.object(sys,'argv',['test','--from-analysis']),contextlib.redirect_stdout(io.StringIO()):
                runpy.run_path(str(BASE/'hh-dash.py'),run_name='__main__')
            data=json.loads((base/'statistics.json').read_text())['dashboard'];status={'generated_at':data['gen'],'heavy_generated_at':data['heavy']['gen'],'funnel':data['funnel']}
            self.assertEqual(status['generated_at'],at)
            self.assertEqual(status['heavy_generated_at'],at)
            self.assertEqual(status['funnel']['sent'],1)

    def test_failed_dashboard_preserves_existing_html(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);(base/'hh-dashboard.html').write_text('previous')
            with patch.object(common,'BASE',base),patch.object(common,'HH_CONFIG',base),patch.object(common,'hh_read_json',side_effect=RuntimeError('API unavailable')),patch.object(sys,'argv',['test']),contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):runpy.run_path(str(BASE/'hh-dash.py'),run_name='__main__')
            self.assertEqual((base/'hh-dashboard.html').read_text(),'previous')

    def console(self,base):
        (base/'.state').mkdir();(base/'logs').mkdir()
        (base/'giga_profile.json').write_text(json.dumps({'name':'Егор','city':'Москва'}))
        (base/'setup.html').write_text((BASE/'setup.html').read_text())
        with patch.object(common,'BASE',base):return runpy.run_path(str(BASE/'setup_console.py'),run_name='audit_console')

    def test_console_protects_api_and_serves_only_reports(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);m=self.console(base);c=m['app'].test_client();kw={'base_url':'http://127.0.0.1:8768'}
            self.assertEqual(c.get('/api/status',**kw).status_code,401)
            self.assertEqual(c.get('/reports/dashboard',**kw).status_code,401)
            self.assertEqual(c.get('/',**kw).status_code,200)
            (base/'hh-dashboard.html').write_text('<h1>Dashboard</h1>')
            (base/'statistics.json').write_text(json.dumps({'schema_version':1,'revision':1,'dashboard':{'gen':'2026-10-14T14:00:00Z','mode':'full','funnel':{'sent':0,'invited':0,'rejected':0,'pending':0,'other':0},'heavy':{}}}))
            response=c.get('/reports/dashboard',**kw)
            self.assertEqual(response.status_code,200)
            response.close()
            headers={'X-Console-Key':m['key']}
            self.assertEqual(c.get('/api/status',headers=headers,**kw).status_code,200)
            self.assertEqual(c.get('/api/status',headers={**headers,'Origin':'https://other.example'},**kw).status_code,403)
            self.assertEqual(c.post('/api/reports/apply/refresh',headers=headers,**kw).status_code,400)
            self.assertEqual(c.get('/reports/arbitrary',**kw).status_code,404)

    def test_report_runner_allowlist_and_pdf_requires_dashboard(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);m=self.console(base);c=m['app'].test_client();kw={'base_url':'http://127.0.0.1:8768','headers':{'X-Console-Key':m['key']}}
            c.get('/',base_url=kw['base_url'])
            self.assertEqual(c.post('/api/reports/pdf/refresh',**kw).status_code,409)
            g=m['run_report'].__globals__;g['report_job']={'status':'running'}
            with patch('subprocess.run',return_value=Mock(returncode=0)) as runner:
                g['run_report']('dashboard')
                self.assertEqual([c.args[0][2:] for c in runner.call_args_list],[['hh-dash.py'],['hh-activity.py']])
                self.assertEqual(g['report_job']['status'],'completed')

    def test_activity_includes_verified_batch_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);folder=base/'.state/batches/test';folder.mkdir(parents=True)
            (folder/'dispatch.json').write_text(json.dumps({'results':[{'id':'1','negotiation_id':'n1','status':'verified','letter':'Текст'}]}))
            runs=base/'.state/runs';runs.mkdir()
            (runs/'hh-test.json').write_text(json.dumps({'action':'apply','results':[{'vacancy_id':'2','status':'sent'},{'vacancy_id':'3','status':'preview'}]}))
            with patch.object(common,'BASE',base),patch.object(common,'HH_CONFIG',base),contextlib.redirect_stdout(io.StringIO()):
                m=runpy.run_path(str(BASE/'hh-activity.py'))
            self.assertEqual(m['verified_batches'],1)
            self.assertEqual(m['batch_letters'],1)
            self.assertEqual(m['recorded_apps'],2)
            self.assertEqual(m['recorded_previews'],1)
            self.assertIn('откликов подтверждено в партиях',(base/'hh-activity.html').read_text())

if __name__=='__main__':
    with patch.object(socket.socket,'connect',side_effect=AssertionError('Сеть запрещена в тестах')):
        unittest.main(verbosity=2)
