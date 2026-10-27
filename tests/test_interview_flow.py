import sys,unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
from interview_flow import closing_reply,dialogue_guidance,history_key
class InterviewFlowTests(unittest.TestCase):
    def test_closing_is_not_a_technical_statement(self):
        self.assertTrue(closing_reply('Пока других вопросов нет, спасибо.'))
        self.assertFalse(closing_reply('Для API использую ограничение контекста.'))
    def test_prior_example_is_not_repeated(self):
        self.assertIn('не начинай с него снова',dialogue_guidance([{'role':'assistant','content':'Оркестрация субагентов'}]))
    def test_histories_are_scoped_to_employer_and_vacancy(self):
        self.assertNotEqual(history_key({'name':'СА','company':'А'}),history_key({'name':'СА','company':'Б'}))
if __name__=='__main__':unittest.main()
