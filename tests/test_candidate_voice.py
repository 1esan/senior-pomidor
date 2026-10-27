import unittest
from candidate import build_system_prompt,reply_problem
class CandidateVoiceTests(unittest.TestCase):
    def test_private_policy_is_not_sent_to_model(self):
        s=build_system_prompt({'name':'Егор','resume_text':'Опыт','job_search_reason':'Проект в поддержке','excluded_employers':['SECRET_EMPLOYER'],'metrics_confirmed_at':'SECRET_DATE'})
        self.assertIn('Проект в поддержке',s)
        self.assertNotIn('SECRET_EMPLOYER',s)
        self.assertNotIn('SECRET_DATE',s)
    def test_internal_fact_language_is_rejected(self):
        for s in ['Отвечу по подтверждённой информации.','В моём резюме не указан такой опыт.','Отвечу по данным профиля.']:
            self.assertIsNotNone(reply_problem(s),s)
    def test_missing_fact_is_rejected(self):
        self.assertIsNotNone(reply_problem('NEEDS_USER'))
    def test_normal_reply_is_allowed(self):
        self.assertIsNone(reply_problem('Проект перешёл на этап поддержки, поэтому рассматриваю новые предложения.'))
