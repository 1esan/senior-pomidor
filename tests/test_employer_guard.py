import argparse
import ast
import asyncio
import contextlib
import io
import json
from pathlib import Path
import runpy
import socket
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
import common
from employer_guard import ContactBlocked, contact_reason, ensure_contact, guard_negotiation, excluded_ids
import hh

TEST_PROFILE={'profile_confirmed':True,'employer_contact_policy':{'strict':True},'excluded_employers':[{'company':'Example Employer Zephyr','aliases':['Example Employer Zephyr','Zephyr','Зефир'],'hh_ids':['990000001','990000002']}]}

def vacancy(name='Example Employer Allowed',eid='990000003'):
    return {'id':'v1','name':'Системный аналитик','employer':{'id':eid,'name':name},'description':'Разработка API'}

class GuardTests(unittest.TestCase):
    def test_configured_ids_are_blocked(self):
        self.assertEqual(set(excluded_ids(TEST_PROFILE)),{'990000001','990000002'})
        for eid in excluded_ids(TEST_PROFILE):
            with self.subTest(eid=eid):
                self.assertIsNotNone(contact_reason(vacancy('Unrelated Example Org',eid),TEST_PROFILE))

    def test_aliases_transliterations_typos(self):
        for name in ['Example Employer Zephyr','Zephyr Analytics','Зефир Данные','Zephry Labs']:
            with self.subTest(name=name):self.assertIsNotNone(contact_reason(vacancy(name),TEST_PROFILE))
        self.assertIsNone(contact_reason(vacancy('Сбер'),TEST_PROFILE))
        self.assertIsNone(contact_reason(vacancy('Example Employer Allowed'),TEST_PROFILE))

    def test_description_conversation_and_links_blocked(self):
        for text in ['Проект для Example Employer Zephyr','Клиент — Example Employer Zephyr','https://nn.hh.ru/employer/990000001?tab=VACANCIES','employer_id=990000002']:
            with self.subTest(text=text):
                self.assertIsNotNone(contact_reason(dict(vacancy(),description=text),TEST_PROFILE))
                with self.assertRaises(ContactBlocked):ensure_contact(vacancy(),TEST_PROFILE,context=text)

    def test_unknown_configuration_and_target_fail_closed(self):
        for name in ['', '?', 'Unknown', 'Не указана']:
            with self.subTest(name=name):self.assertIsNotNone(contact_reason(vacancy(name),TEST_PROFILE))
        self.assertIsNotNone(contact_reason(vacancy(),profile={}))
        self.assertIsNotNone(contact_reason(dict(vacancy(),description='Наш клиент — крупный банк'),TEST_PROFILE))

    def test_search_excludes_ids_and_stays_dry_run(self):
        args=argparse.Namespace(action='apply',resume_id=None,query='аналитик',max=1,live=False)
        cmd=hh.build_command(args,TEST_PROFILE)
        self.assertIn('--excluded-employer-id',cmd)
        self.assertIn('--dry-run',cmd)
        for eid in excluded_ids(TEST_PROFILE):self.assertIn(eid,cmd)

    def test_fresh_negotiation_and_employer_messages_checked(self):
        v=vacancy()
        def api(method,path):
            if path.startswith('/negotiations?page='):return 200,{'pages':1,'items':[{'id':'1','vacancy':v}]}
            if path=='/vacancies/v1':return 200,v
            if path.startswith('/negotiations/1/messages'):return 200,{'pages':1,'items':[{'author':{'participant_type':'employer'},'text':'Вакансия для Example Employer Zephyr'}]}
            raise AssertionError(path)
        with patch('employer_guard.load_profile',return_value=TEST_PROFILE),self.assertRaises(ContactBlocked):guard_negotiation('1',api)
        with self.assertRaises(ContactBlocked):guard_negotiation('1',lambda *a:(401,{}))
        with self.assertRaises(ContactBlocked):guard_negotiation('2',lambda *a:(200,{'pages':1,'items':[]}))

    def test_both_broadcast_helpers_block_before_http_post(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)
            (base/'auth.json').write_text(json.dumps({'token':{'access_token':'offline'}}))
            (base/'hh-data.json').write_text(json.dumps({'rows':[]}))
            with patch.object(common,'BASE',base),patch.object(common,'HH_CONFIG',base),patch.object(sys,'argv',['offline']),contextlib.redirect_stdout(io.StringIO()):
                blast=runpy.run_path(str(BASE/'hh-tg-blast.py'),run_name='offline')
                bump=runpy.run_path(str(BASE/'hh-bump16.py'),run_name='offline')
            for fn,args in [(blast['api'],('POST','/negotiations/1/messages',{'message':'Тест'})),(bump['post'],('1','Тест'))]:
                fn.__globals__['guard_negotiation']=Mock(side_effect=ContactBlocked('Запрет'))
                with patch('employer_guard.guard_negotiation',side_effect=ContactBlocked('Запрет')),patch('urllib.request.urlopen') as network:
                    with self.assertRaises(ContactBlocked):fn(*args)
                    network.assert_not_called()

    def test_telegram_blocks_text_buttons_and_unknown_menu(self):
        tree=ast.parse((BASE/'giga-bot.py').read_text())
        names={'ensure_telegram_contact','type_and_send','click_button','choose_vacancy','clean_label','vac_key'}
        funcs=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
        import re
        from employer_guard import extract_company
        g={'contact_reason':lambda v,profile=None,context='':contact_reason(v,TEST_PROFILE,context),'ContactBlocked':ContactBlocked,'extract_company':extract_company,'resolve_company':extract_company,'re':re,
           'CUR_VACANCY':{'name':'Системный аналитик','company':'Example Employer Zephyr','blocked':None},
           'JUNK_BTN':('далее','меню'), 'VACANCY_WORD_RE':re.compile(r'аналитик|analyst',re.I),'VACANCY_STRATEGY':'first'}
        exec(compile(ast.Module(body=funcs,type_ignores=[]),'offline_telegram','exec'),g)
        page=Mock()
        for fn,args in [(g['type_and_send'],(page,'Тест',False)),(g['click_button'],(page,'Да',False))]:
            with self.assertRaises(ContactBlocked):asyncio.run(fn(*args))
            self.assertEqual(page.mock_calls,[])
        g['CUR_VACANCY']['company']=None
        with self.assertRaises(ContactBlocked):g['ensure_telegram_contact']()
        self.assertIsNone(g['choose_vacancy'](['Системный аналитик'],set()))
        self.assertIsNone(g['choose_vacancy'](['Системный аналитик\nКомпания: Example Employer Zephyr'],set()))
        good='Системный аналитик\nКомпания: Example Employer Allowed'
        self.assertEqual(g['choose_vacancy']([good],set()),good)

    def test_hh_reply_skips_blocked_chat_before_read_or_post(self):
        from hh_applicant_tool.operations.reply_employers import Operation
        op=Operation();op.tool=Mock();op.api_client=Mock();op.period=0;op.only_invitations=False
        op.tool.get_negotiations.return_value=[{'id':'n1','resume':{'id':'r'},'updated_at':'2000-01-02T12:00:00+03:00','state':{'id':'response'},'vacancy':vacancy('Example Employer Zephyr','990000001')}]
        op.tool.employer_contact_guard.side_effect=lambda v,*args:ensure_contact(v,TEST_PROFILE)
        with contextlib.redirect_stdout(io.StringIO()):op._reply_chats({},[{'id':'r','title':'СА'}],set())
        op.api_client.get.assert_not_called()
        op.api_client.post.assert_not_called()

if __name__=='__main__':
    with patch.object(socket.socket,'connect',side_effect=AssertionError('Сеть запрещена в тестах')):
        unittest.main(verbosity=2)
