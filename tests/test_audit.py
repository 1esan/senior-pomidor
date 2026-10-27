import argparse
import asyncio
import ast
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import runpy
import socket
import sys
import tempfile
import unittest
from unittest.mock import Mock, AsyncMock, patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import common
import hh
from vacancy_policy import vacancy_decision
from employer_guard import contact_reason
from hh_applicant_tool.operations.apply_vacancies import Operation
from hh_applicant_tool.ai.openai import ChatOpenAI

PROFILE = dict(profile_confirmed=True, salary_min='280000', salary_max='320000',
               work_formats=['Удалёнка', 'Гибрид', 'Офис'], office_cities='Москва',
               mobility=['Переезд возможен'], resume_text='Подтверждённый опыт системного анализа',
               excluded_employers=[{'company':'Запрещённая компания','hh_ids':['999'], 'aliases':['Запрещённая компания']}],
               employer_contact_policy={'strict':True})

def vacancy(vid='1', city='Москва', formats=('ON_SITE',), salary=True):
    return dict(id=vid, name='Системный аналитик', area={'name': city},
                alternate_url='https://hh.ru/vacancy/'+vid, employer={'id':'123','name':'Разрешённая компания'},
                work_format=[{'id':f} for f in formats],
                salary={'from':280000, 'to':320000, 'currency':'RUR', 'gross':False} if salary else None,
                description='<p>Разработка API интеграции</p>', key_skills=[{'name':'SQL'}])

class AuditTests(unittest.TestCase):
    def test_profile_policy(self):
        cases = [
            (vacancy(), 'allow'),
            (vacancy(city='Берлин', formats=('REMOTE',)), 'allow'),
            (vacancy(city='Санкт-Петербург'), 'review'),
            (vacancy(city='Берлин'), 'review'),
            (vacancy(salary=False), 'review'),
            (dict(vacancy(), salary={'to':270000,'currency':'RUR','gross':False}), 'skip'),
            (dict(vacancy(), salary={'to':320000,'currency':'RUR','gross':True}), 'review'),
            (dict(vacancy(), salary={'to':4000,'currency':'USD','gross':False}), 'review'),
            (dict(vacancy(), employer={'name':'Сбер'}), 'allow'),
            (dict(vacancy(), salary={'from':350000,'currency':'RUR','gross':False}), 'allow'),
        ]
        for v, expected in cases:
            with self.subTest(v=v):
                self.assertEqual(vacancy_decision(v, PROFILE)[0], expected)

    def test_hh_prompt_and_preview_without_post(self):
        args = argparse.Namespace(action='apply', resume_id=None, query='системный аналитик', max=1, live=False)
        command = hh.build_command(args, PROFILE)
        self.assertIn('--dry-run', command)
        op = Operation()
        parser = argparse.ArgumentParser()
        op.setup_parser(parser)
        params = parser.parse_args(command[command.index('apply')+1:])
        params.use_ai = True
        tool = Mock()
        tool.application_budget_exhausted=lambda:False
        tool.application_result=None
        tool.config = {}
        tool.candidate_vacancy_policy = lambda v: vacancy_decision(v, PROFILE)
        tool.employer_contact_guard = Mock()
        tool.get_openai_args.return_value = dict(api_key='offline-placeholder', base_url='http://127.0.0.1:8766/v1/chat/completions', model='gpt-6-luna')
        # Реальный конструктор: неизвестный аргумент system_propmpt вызовет ошибку.
        tool.get_ai_client.side_effect = lambda **c: ChatOpenAI(**c)
        with patch.object(op, '_apply_vacancies'):
            op.run(tool, params)
        self.assertIn(PROFILE['resume_text'], op.cover_letter_ai.system_prompt)
        ai = Mock()
        ai.complete.return_value = 'Готов обсудить интеграции API.'
        op.cover_letter_ai = ai
        samples = [vacancy('0',salary=False), vacancy('1'), vacancy('2')]
        tool.api_client.get.side_effect = lambda path: ({'id':'123','name':'Разрешённая компания'} if path.startswith('/employers/') else next(v for v in samples if path.endswith('/'+v['id'])))
        tool.api_client.post.side_effect = AssertionError('POST запрещён в проверке')
        op._get_vacancies = Mock(return_value=iter(samples))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            op._apply_resume({'id':'r','title':'СА','alternate_url':'offline'}, {}, set())
        self.assertEqual(ai.complete.call_count, 1)
        prompt = ai.complete.call_args.args[0]
        self.assertIn('Разработка API интеграции', prompt)
        self.assertIn('SQL', prompt)
        self.assertIn('Предварительный отклик', out.getvalue())
        tool.api_client.post.assert_not_called()
        tool.api_client.put.assert_not_called()

    def test_aggregation_and_bump_read_paths_empty_data(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base/'auth.json').write_text(json.dumps({'token':{'access_token':'offline'}}))
            (base/'hh-data.json').write_text(json.dumps({'generated_at':'2026-10-13T00:00:00+00:00','rows':[]}))
            with patch.object(common,'BASE',base), patch.object(common,'HH_CONFIG',base), patch.object(sys,'argv',['test']), contextlib.redirect_stdout(io.StringIO()):
                runpy.run_path(str(BASE/'hh-agg.py'))
                runpy.run_path(str(BASE/'hh-bump16.py'))
            self.assertEqual(json.loads((base/'statistics.json').read_text())['analysis']['total'],0)

    def test_analysis_refresh_and_failed_refresh_keeps_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base/'auth.json').write_text(json.dumps({'token':{'access_token':'offline'}}))
            with patch.object(common,'BASE',base), patch.object(common,'HH_CONFIG',base):
                module = runpy.run_path(str(BASE/'hh-analyze.py'),run_name='audit_import')
            g=module['main'].__globals__
            g['OUT']=base/'hh-data.json'
            g['time']=Mock()
            g['all_negotiations']=lambda: iter([{'id':'1','state':{'id':'response'},'vacancy':vacancy(),'_status_group':'active'}])
            g['messages']=lambda _: [{'who':'employer','text':'Вопрос','at':'2026-10-13T12:00:00Z'}]
            with contextlib.redirect_stdout(io.StringIO()):g['main']()
            self.assertEqual(json.loads(g['OUT'].read_text())['rows'][0]['state'],'response')
            g['all_negotiations']=lambda: iter([{'id':'1','state':{'id':'invitation'},'vacancy':vacancy(),'_status_group':'active'}])
            with contextlib.redirect_stdout(io.StringIO()):g['main']()
            self.assertEqual(json.loads(g['OUT'].read_text())['rows'][0]['state'],'invitation')
            previous=g['OUT'].read_text()
            g['all_negotiations']=Mock(side_effect=RuntimeError('Нет доступа к API'))
            with self.assertRaises(RuntimeError):g['main']()
            self.assertEqual(g['OUT'].read_text(),previous)

    def test_activity_distinguishes_preview_and_submission(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);(base/'logs').mkdir()
            (base/'logs/giga-bot.log').write_text('2026-10-13 12:00:00 INFO TELEGRAM_PREVIEW: Тест\n2026-10-13 12:00:01 INFO TELEGRAM_ATTEMPT: Тест\n2026-10-13 12:00:02 INFO TELEGRAM_SUBMITTED: Enter нажат\n')
            with patch.object(common,'BASE',base), patch.object(common,'HH_CONFIG',base), contextlib.redirect_stdout(io.StringIO()):
                results=runpy.run_path(str(BASE/'hh-activity.py'))
            self.assertEqual(results['tot']['giga'],1)
            self.assertEqual(results['tot']['giga_preview'],1)

    def test_telegram_log_requires_enter_and_dry_run_does_not_type(self):
        tree=ast.parse((BASE/'giga-bot.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='type_and_send')
        module=ast.Module(body=[fn],type_ignores=[])
        fake_async=Mock();fake_async.sleep=AsyncMock()
        g={'STATE_PATH':None,'CURRENT_MESSAGE':'test','log':Mock(),'asyncio':fake_async,'random':Mock(),'INPUT_SEL':'offline','ensure_telegram_contact':Mock(),'assert_target':AsyncMock(),'check_deadline':Mock(),'WEB_DEADLINE':9999999999,'TARGET_PEER':'8491767152','require_current_question':AsyncMock(return_value={'mid':'1','source_text':'Тест'}),'require_empty_editor':AsyncMock(),'dispatch':AsyncMock(return_value='8491767152'),'SEND_JS':'offline'}
        exec(compile(module,'offline_giga','exec'),g)
        page=Mock();page.keyboard.press=AsyncMock();page.keyboard.type=AsyncMock();page.locator.return_value.first.click=AsyncMock();page.locator.return_value.fill=AsyncMock()
        asyncio.run(g['type_and_send'](page,'Тест',True))
        page.keyboard.press.assert_not_called()
        self.assertIn('TELEGRAM_PREVIEW',g['log'].info.call_args.args[0])
        g['log'].reset_mock()
        asyncio.run(g['type_and_send'](page,'Тест',False))
        self.assertIn('TELEGRAM_SUBMITTED',g['log'].info.call_args.args[0])
        g['log'].reset_mock()
        g['dispatch'].side_effect=RuntimeError('Браузер закрыт')
        with self.assertRaises(RuntimeError):asyncio.run(g['type_and_send'](page,'Тест',False))
        self.assertFalse(any('TELEGRAM_SUBMITTED' in c.args[0] for c in g['log'].info.call_args_list))

if __name__ == '__main__':
    # Любой случайный сетевой запрос немедленно блокируется.
    with patch.object(socket.socket,'connect',side_effect=AssertionError('Сеть запрещена в локальных тестах')):
        unittest.main(verbosity=2)
