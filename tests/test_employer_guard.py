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
from candidate import load_profile
from employer_guard import ContactBlocked, contact_reason, ensure_contact, guard_negotiation, excluded_ids
import hh

def vacancy(name='Разрешённая компания',eid='123'):
    return {'id':'v1','name':'Системный аналитик','employer':{'id':eid,'name':name},'description':'Разработка API'}

class GuardTests(unittest.TestCase):
    def test_all_five_ids_are_blocked(self):
        profile=load_profile()
        self.assertEqual(set(excluded_ids(profile)),{'1833','5398961','5063336','8582','1658451'})
        for eid in excluded_ids(profile):
            with self.subTest(eid=eid):
                self.assertIsNotNone(contact_reason(vacancy('Иное название',eid)))

    def test_aliases_transliterations_typos(self):
        for name in ['БКС IT & Digital','БКC Банк','BKS','BCS Capital','БрокерКредитСервис','БКС Нефтехим',
                     'FLOW-WOW','Flow Wow','Flowwo','Флаувау Рус','Флоу-вау',
                     'Лемана Тех','Lemona','Leroi Merlin','LEMANA.PRO','Leroy Merlin','Лерой Мерлен','ЛЕ МОНЛИД ЦИФРОВЫЕ ТЕХНОЛОГИИ','LeMonlid']:
            with self.subTest(name=name):self.assertIsNotNone(contact_reason(vacancy(name)))
        self.assertIsNone(contact_reason(vacancy('Сбер')))
        self.assertIsNone(contact_reason(vacancy('Разрешённая компания')))

    def test_description_conversation_and_links_blocked(self):
        for text in ['Проект для Flowwow','Клиент — Лемана Тех','https://nn.hh.ru/employer/1833?tab=VACANCIES','employer_id=8582']:
            with self.subTest(text=text):
                self.assertIsNotNone(contact_reason(dict(vacancy(),description=text)))
                with self.assertRaises(ContactBlocked):ensure_contact(vacancy(),context=text)

    def test_unknown_configuration_and_target_fail_closed(self):
        for name in ['', '?', 'Unknown', 'Не указана']:
            with self.subTest(name=name):self.assertIsNotNone(contact_reason(vacancy(name)))
        self.assertIsNotNone(contact_reason(vacancy(),profile={}))
        self.assertIsNotNone(contact_reason(dict(vacancy(),description='Наш клиент — крупный банк')))

    def test_search_excludes_ids_and_stays_dry_run(self):
        args=argparse.Namespace(action='apply',resume_id=None,query='аналитик',max=1,live=False)
        cmd=hh.build_command(args,load_profile())
        self.assertIn('--excluded-employer-id',cmd)
        self.assertIn('--dry-run',cmd)
        for eid in excluded_ids(load_profile()):self.assertIn(eid,cmd)

    def test_fresh_negotiation_and_employer_messages_checked(self):
        v=vacancy()
        def api(method,path):
            if path.startswith('/negotiations?page='):return 200,{'pages':1,'items':[{'id':'1','vacancy':v}]}
            if path=='/vacancies/v1':return 200,v
            if path.startswith('/negotiations/1/messages'):return 200,{'pages':1,'items':[{'author':{'participant_type':'employer'},'text':'Вакансия для БКС'}]}
            raise AssertionError(path)
        with self.assertRaises(ContactBlocked):guard_negotiation('1',api)
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
        g={'contact_reason':contact_reason,'ContactBlocked':ContactBlocked,'extract_company':extract_company,'resolve_company':extract_company,'re':re,
           'CUR_VACANCY':{'name':'Системный аналитик','company':'Лемана Тех','blocked':None},
           'JUNK_BTN':('далее','меню'), 'VACANCY_WORD_RE':re.compile(r'аналитик|analyst',re.I),'VACANCY_STRATEGY':'first'}
        exec(compile(ast.Module(body=funcs,type_ignores=[]),'offline_telegram','exec'),g)
        page=Mock()
        for fn,args in [(g['type_and_send'],(page,'Тест',False)),(g['click_button'],(page,'Да',False))]:
            with self.assertRaises(ContactBlocked):asyncio.run(fn(*args))
            self.assertEqual(page.mock_calls,[])
        g['CUR_VACANCY']['company']=None
        with self.assertRaises(ContactBlocked):g['ensure_telegram_contact']()
        self.assertIsNone(g['choose_vacancy'](['Системный аналитик'],set()))
        self.assertIsNone(g['choose_vacancy'](['Системный аналитик\nКомпания: Flowwow'],set()))
        good='Системный аналитик\nКомпания: Разрешённая компания'
        self.assertEqual(g['choose_vacancy']([good],set()),good)

    def test_hh_reply_skips_blocked_chat_before_read_or_post(self):
        from hh_applicant_tool.operations.reply_employers import Operation
        op=Operation();op.tool=Mock();op.api_client=Mock();op.period=0;op.only_invitations=False
        op.tool.get_negotiations.return_value=[{'id':'n1','resume':{'id':'r'},'updated_at':'2026-10-13T12:00:00+03:00','state':{'id':'response'},'vacancy':vacancy('БКС','1833')}]
        op.tool.employer_contact_guard.side_effect=lambda v,*args:ensure_contact(v)
        with contextlib.redirect_stdout(io.StringIO()):op._reply_chats({},[{'id':'r','title':'СА'}],set())
        op.api_client.get.assert_not_called()
        op.api_client.post.assert_not_called()

if __name__=='__main__':
    with patch.object(socket.socket,'connect',side_effect=AssertionError('Сеть запрещена в тестах')):
        unittest.main(verbosity=2)
