import unittest
from candidate import build_system_prompt,reply_problem
class ConciseVoiceTests(unittest.TestCase):
 def test_common_style_exists_in_both_modes(self):
  for screening in (True,False):
   p=build_system_prompt({'name':'Example Candidate','resume_text':'API'},screening=screening)
   self.assertIn('Единый стиль готового ответа',p)
   self.assertIn('Обычно 1–2 коротких предложения',p)
   self.assertNotIn('4–6 коротких предложений',p)
 def test_service_intros_are_rejected(self):
  for text in ['Вот вариант ответа: я работал с API.','Как ИИ, я могу подготовить ответ.','Согласно предоставленному профилю, есть опыт.','В исходных материалах это не указано.','Нужно уточнить у владельца.']:
   with self.subTest(text=text):self.assertIsNotNone(reply_problem(text,{}))
 def test_natural_replies_are_accepted(self):
  for text in ['Рассматриваю предложения от 100 тысяч рублей на руки.','В Example Employer Alpha описывал REST API и события Kafka для тестового сервиса операций.','Для vLLM я бы начал с контракта API и обработки ошибок.','Гибрид подходит. Сколько дней нужно быть в офисе?']:
   with self.subTest(text=text):self.assertIsNone(reply_problem(text,{}))
if __name__=='__main__':unittest.main()
