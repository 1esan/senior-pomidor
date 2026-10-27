import argparse,asyncio,contextlib,importlib.util,io,json,runpy,socket,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,AsyncMock,patch
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
import common,hh,runtime,operations,profile_editor,telegram_state
from hh_applicant_tool.operations.apply_vacancies import Operation as Apply
from hh_applicant_tool.operations.reply_employers import Operation as Reply
from employer_guard import ContactBlocked
PROFILE=dict(profile_confirmed=True,name='Егор',city='Москва',phone='+7',telegram='@x',salary_min=280000,salary_max=320000,resume_text='Подтверждённый опыт системного аналитика, Kafka и REST API',work_formats=['Офис','Гибрид','Удалёнка'],office_cities=['Москва'],employment_types=[],mobility=['Переезд возможен'],military_id=None,business_travel=None,employer_contact_policy={'strict':True},excluded_employers=[{'company':'БКС','hh_ids':['1833'],'aliases':['БКС']}])
def vac(i,employer='Разрешённая организация'):
    return {'id':str(i),'name':'Системный аналитик','employer':{'id':'123','name':employer},'alternate_url':'https://hh.ru/vacancy/'+str(i),'work_format':[{'id':'ON_SITE'}],'area':{'name':'Москва'},'salary':{'from':280000,'to':320000,'currency':'RUR','gross':False},'description':'REST API','key_skills':[{'name':'Kafka'}]}

class MigrationTests(unittest.TestCase):
    def test_all_old_search_options_parse_and_map(self):
        a=hh.parser().parse_args(['apply','--all-queries','--pages','3','--per-page','100','--body-too','--employer-id','3529','--preset','ru-cis','--no-sber'])
        c=hh.build_command(a,PROFILE)
        self.assertIn('description',c);self.assertIn('REMOTE',c);self.assertIn('3529',c);self.assertIn('--dry-run',c);self.assertEqual(len(hh.DEFAULT_QUERIES),14)
        p=argparse.ArgumentParser();Apply().setup_parser(p);parsed=p.parse_args(c[c.index('apply')+1:]);self.assertEqual(parsed.total_pages,3);self.assertEqual(parsed.per_page,100)

    def test_global_budget_covers_multiple_queries_and_deduplicates(self):
        a=hh.parser().parse_args(['apply','--queries','первый','второй','третий','--max','2'])
        fake=Mock();fake.api_client=Mock();calls=[]
        def run(c):
            q=c[c.index('--search')+1];calls.append(q)
            for v in ([vac(1)] if q=='первый' else [vac(1),vac(2),vac(3)]):
                if fake.application_budget_exhausted():break
                if fake.candidate_vacancy_policy(v)[0]=='allow':fake.application_result(v,'Личное письмо',True)
            return 0
        fake.run.side_effect=run
        with tempfile.TemporaryDirectory() as d,patch.object(hh,'BASE',Path(d)),patch.object(hh,'load_profile',return_value=PROFILE),patch.object(hh,'hh_tool',return_value=fake),patch.object(runtime,'BASE',Path(d)):
            self.assertEqual(hh.run(a),0)
            state=json.loads(next((Path(d)/'.state/runs').glob('*.json')).read_text())
            self.assertEqual(len(state['results']),2);self.assertEqual(calls,['первый','второй']);self.assertEqual([r['vacancy_id'] for r in state['results']],['1','2']);fake.api_client.post.assert_not_called()

    def test_global_budget_stops_at_second_resume(self):
        op=Apply();t=Mock();t.application_budget_exhausted.side_effect=[False,True];t.get_resumes.return_value=[{'id':'a','status':{'id':'published'}},{'id':'b','status':{'id':'published'}}]
        op.tool=t;op.resume_id=None;op.dry_run=True;op._apply_resume=Mock(return_value=False)
        with contextlib.redirect_stdout(io.StringIO()):op._apply_vacancies()
        self.assertEqual(op._apply_resume.call_count,1)

    def test_loop_is_finite_and_stops_on_failure(self):
        now=[0.];passes=[]
        def sleep(n):now[0]+=n
        def fn():passes.append(now[0]);return 0
        self.assertEqual(runtime.repeat_pass(fn,10,300,lambda:now[0],sleep),0);self.assertEqual(passes,[0.,300.])
        failed=Mock(return_value=1);self.assertEqual(runtime.repeat_pass(failed,60,300),1);failed.assert_called_once()

    def test_concurrent_channel_is_rejected(self):
        with tempfile.TemporaryDirectory() as d,patch.object(runtime,'BASE',Path(d)):
            with runtime.operation_lock('hh'):
                with self.assertRaises(RuntimeError):
                    with runtime.operation_lock('hh'):pass

    def test_profile_preserves_categorical_bans_and_unknowns(self):
        p=profile_editor.update_profile(PROFILE,{'city':'Москва','profile_confirmed':True})
        self.assertEqual(p['excluded_employers'],PROFILE['excluded_employers']);self.assertIsNone(p['military_id']);self.assertIsNone(p['business_travel'])
        with self.assertRaises(ValueError):profile_editor.update_profile(PROFILE,{'excluded_employers':[]})
        with self.assertRaises(ValueError):profile_editor.update_profile(PROFILE,{'salary_min':400000})
        with self.assertRaises(ValueError):profile_editor.update_profile(PROFILE,{'profile_confirmed':False})

    def test_resume_docx_tables_and_pdf_extraction(self):
        from docx import Document
        d=Document();d.add_paragraph('Системный аналитик: подтверждённый опыт Kafka и REST API');d.add_table(rows=1,cols=1).cell(0,0).text='Проект банка';b=io.BytesIO();d.save(b)
        t=profile_editor.extract_text('resume.docx',b.getvalue());self.assertIn('Проект банка',t)
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
        w=PdfWriter();p=w.add_blank_page(width=200,height=200)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        p[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
        stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 10 100 Td (System analyst Kafka REST API confirmed experience) Tj ET');p[NameObject('/Contents')]=w._add_object(stream)
        b=io.BytesIO();w.write(b);self.assertIn('System analyst',profile_editor.extract_text('resume.pdf',b.getvalue()))
        with self.assertRaises(ValueError):profile_editor.extract_text('resume.exe',b'bad')
        with self.assertRaises(ValueError):profile_editor.extract_text('resume.txt',b'')

    def test_telegram_persistent_uncertain_action_prevents_retries(self):
        with tempfile.TemporaryDirectory() as d,patch.object(telegram_state,'BASE',Path(d)):
            path,state=telegram_state.load_state('web',False);telegram_state.begin_action(path,state,'mid:button')
            _,after=telegram_state.load_state('web',False)
            with self.assertRaises(RuntimeError):telegram_state.begin_action(path,after,'mid:button')
            _,preview=telegram_state.load_state('web',True);self.assertEqual(preview['actions'],{})
            b={'mid':'1','text':'Меню','buttons':['A']};self.assertNotEqual(telegram_state.fingerprint(b),telegram_state.fingerprint({**b,'buttons':['B']}))

    def test_verified_binding_rejects_forbidden_company(self):
        with tempfile.TemporaryDirectory() as d,patch.object(telegram_state,'BASE',Path(d)),patch.object(telegram_state,'hh_read_json',return_value=vac(1,'БКС')),patch('employer_guard.load_profile',return_value=PROFILE):
            with self.assertRaises(ContactBlocked):telegram_state.bind('Системный аналитик','1',True)
            self.assertFalse((Path(d)/'.state/telegram-bindings.json').exists())

    def test_only_explicit_live_and_allowlisted_commands(self):
        with self.assertRaises(ValueError):operations.command_for('apply',{'mode':'live'})
        with self.assertRaises(ValueError):operations.command_for('arbitrary',{})
        with self.assertRaises(ValueError):operations.command_for('apply',{'queries':'--live'})
        c,ch=operations.command_for('reply',{'minutes':60,'interval':300})
        self.assertNotIn('--live',c);self.assertIn('--loop-minutes',c)
        c,ch=operations.command_for('apply',{'mode':'live','confirm_live':True,'queries':'системный аналитик','max':5})
        self.assertIn('--live',c)

    def test_live_helper_rechecks_guard_before_any_post(self):
        with patch('employer_guard.guard_negotiation',side_effect=ContactBlocked('Запрет')),patch.object(common,'hh_tool') as tool:
            with self.assertRaises(ContactBlocked):common.hh_exchange('POST','/negotiations/1/messages',{'message':'Текст'})
            tool.assert_not_called()

    def test_schedule_is_exported_disabled_and_preview(self):
        import bot_cli,plistlib
        with tempfile.TemporaryDirectory() as d,patch.object(bot_cli,'BASE',Path(d)):
            f=bot_cli.prepare_schedule();cfg=plistlib.loads(f.read_bytes())
            self.assertTrue(cfg['Disabled']);self.assertNotIn('--live',cfg['ProgramArguments']);self.assertEqual([x['Hour'] for x in cfg['StartCalendarInterval']],[9,13,17,21])

    def test_telethon_transport_dry_run_and_unsafe_button(self):
        spec=importlib.util.spec_from_file_location('tele_test',BASE/'giga-recruiter.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        e=Mock();e.TARGET_PEER="8491767152";c=Mock();c.send_message=AsyncMock();t=m.TelethonTransport(c,Mock(id=8491767152),e)
        asyncio.run(t.send(None,'Ответ',True));c.send_message.assert_not_called()
        asyncio.run(t.click(None,'Да',True));e.ensure_telegram_contact.assert_called()

    def test_stop_only_targets_registered_child_group(self):
        p=Mock();p.pid=123;p.poll.return_value=None
        j={'id':'test','status':'running','process':p}
        with patch.object(operations,'JOBS',{'test':j}),patch('operations.os.killpg') as kill,patch('operations.threading.Thread'):
            operations.stop('test');kill.assert_called_once_with(123,operations.signal.SIGINT)
            with self.assertRaises(ValueError):operations.stop('arbitrary')

    def test_reply_newest_applicant_message_prevents_response(self):
        op=Reply();op.tool=Mock();op.api_client=Mock();op.dry_run=True;op.period=0;op.max_pages=1;op.only_invitations=False
        n={'id':'n','updated_at':'2026-10-14T00:00:00+03:00','state':{'id':'response'},'resume':{'id':'r'},'vacancy':vac(1)}
        op.tool.get_negotiations.return_value=[n];op.tool.employer_contact_guard.return_value=vac(1)
        op.api_client.get.return_value={'pages':1,'items':[{'id':'2','created_at':'2026-10-14T02:00:00+03:00','author':{'participant_type':'applicant'},'text':'Уже ответил'}, {'id':'1','created_at':'2026-10-14T01:00:00+03:00','author':{'participant_type':'employer'},'text':'Вопрос?'}]}
        with tempfile.TemporaryDirectory() as d:
            op.tool.config_dir_path=Path(d);op.reply_chat_ai=Mock()
            with contextlib.redirect_stdout(io.StringIO()):op._reply_chats({},[{'id':'r','title':'СА'}],set())
            op.reply_chat_ai.complete.assert_not_called();op.api_client.post.assert_not_called()

    def test_resume_upload_and_api_credentials_are_not_echoed(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);(base/'.state').mkdir();(base/'logs').mkdir();(base/'giga_profile.json').write_text(json.dumps(PROFILE));(base/'setup.html').write_text('__KEY__')
            with patch.object(common,'BASE',base):m=runpy.run_path(str(BASE/'setup_console.py'),run_name='test_console_full')
            c=m['app'].test_client();kw={'base_url':'http://127.0.0.1:8768','headers':{'X-Console-Key':m['key']}}
            r=c.post('/api/resume/extract',data={'resume':(io.BytesIO(b'Confirmed systems analysis Kafka REST API experience'),'resume.txt')},**kw)
            self.assertEqual(r.status_code,200);self.assertIn('Confirmed',r.json['text'])
            r=c.post('/api/telethon',json={'api_id':123,'api_hash':'a'*32},**kw);self.assertEqual(r.status_code,200)
            self.assertNotIn('a'*32,c.get('/api/telethon',**kw).get_data(as_text=True))
            self.assertEqual(c.post('/api/operations/apply/start',json={'mode':'live'},**kw).status_code,400)

if __name__=='__main__':
    with patch.object(socket.socket,'connect',side_effect=AssertionError('Сеть запрещена в тестах')):unittest.main(verbosity=2)
