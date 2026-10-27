import ast,sys,unittest
from pathlib import Path
from unittest.mock import Mock
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
from candidate import build_system_prompt,reply_problem
from autonomous_runtime import NeedsDecision

class ScreeningDialogueTests(unittest.TestCase):
    def test_relaxation_is_limited_to_screening(self):
        p={'name':'Егор','resume_text':'Оркестрация сабагентов в личном проекте'}
        self.assertIn('Если спросили о конкретном опыте и ответ невозможно',build_system_prompt(p))
        relaxed=build_system_prompt(p,screening=True)
        self.assertNotIn('Если спросили о конкретном опыте и ответ невозможно',relaxed)
        self.assertIn('Личные AI-проекты',relaxed)
        self.assertIn('не принимай оффер',relaxed)

    def cleaner(self):
        tree=ast.parse((BASE/'giga-bot.py').read_text())
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('_strip_echo','clean_text_reply')]
        g={'reply_problem':reply_problem,'NeedsDecision':NeedsDecision,'LEAK_MARKERS':('сообщение рекрутёра',)}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'offline','exec'),g)
        return g['clean_text_reply']

    def test_missing_detail_gets_a_second_generation(self):
        retry=Mock(return_value='В личном проекте распределял задачи между агентами и проверял результат.')
        self.assertEqual(self.cleaner()('NEEDS_USER',retry),retry.return_value)
        retry.assert_called_once()

    def test_meta_language_is_rewritten(self):
        retry=Mock(return_value='Я разделяю выполнение задачи и проверку результата.')
        self.assertEqual(self.cleaner()('В моём резюме не указан такой опыт.',retry),retry.return_value)

    def test_internal_signal_never_becomes_an_outgoing_message(self):
        retry=Mock(return_value='NEEDS_USER')
        with self.assertRaises(NeedsDecision):self.cleaner()('NEEDS_USER',retry)
        self.assertEqual(retry.call_count,2)

if __name__=='__main__':unittest.main()
