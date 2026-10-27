import ast,json,sys,unittest
from pathlib import Path
from unittest.mock import Mock
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
from candidate import build_system_prompt,reply_problem,load_profile
from autonomous_runtime import NeedsDecision
from profile_editor import update_profile

class AnswerVoiceUpgradeTests(unittest.TestCase):
 def profile(self):return {'screening_answers':'BI-инструменты не использовал.\nPython/Java, Docker/Kubernetes: серьёзного релевантного опыта нет.\nИИ: использовал Claude.'}
 def cleaner(self):
  nodes=[n for n in ast.parse((BASE/'giga-bot.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name in ('_strip_echo','clean_text_reply')]
  scope={'reply_problem':lambda t:reply_problem(t,self.profile()),'NeedsDecision':NeedsDecision,'LEAK_MARKERS':('сообщение рекрутёра',)}
  exec(compile(ast.Module(body=nodes,type_ignores=[]),'offline','exec'),scope);return scope['clean_text_reply']
 def test_leaked_policy_variations_are_rewritten(self):
  for text in ['У меня нет отдельного подтверждённого проекта.','Конкретные модели и инструменты не назову.','Конкретные инструменты не заданы.','Этот опыт не подтверждён.']:
   with self.subTest(text=text):self.assertIsNotNone(reply_problem(text,self.profile()))
 def test_missing_sdk_and_visio_are_not_negative_facts(self):
  for text in ['Visio в этих проектах не применял.','Отдельно аналитику внутри mobile SDK не проектировал.','У меня нет практического опыта с SDK.']:
   with self.subTest(text=text):self.assertIsNotNone(reply_problem(text,self.profile()))
 def test_explicit_negative_facts_remain_valid(self):
  for text in ['BI-инструменты не использовал.','BI не использовал.','Docker не использовал.']:
   with self.subTest(text=text):self.assertIsNone(reply_problem(text,self.profile()))
 def test_known_bi_negative_cannot_justify_unknown_visio_negative(self):
  self.assertIsNotNone(reply_problem('Visio и BI не использовал.',self.profile()))
 def test_technical_negation_is_not_a_personal_denial(self):
  self.assertIsNone(reply_problem('Идемпотентность не позволяет повторно выполнить операцию.',self.profile()))
 def test_transferable_experience_and_hypothetical_approach_allowed(self):
  self.assertIsNone(reply_problem('Мой основной опыт — финансовые backend-интеграции. Для SDK я бы описал каталог событий и версии контракта.',self.profile()))
 def test_rewrite_occurs_before_returning_text(self):
  retry=Mock(return_value='В БКС использовал Claude для ревью API-контрактов.')
  self.assertEqual(self.cleaner()('Конкретные модели и инструменты не назову.',retry),retry.return_value);retry.assert_called_once()
 def test_unknown_negative_triggers_rewrite(self):
  retry=Mock(return_value='В проектах прорабатывал событийные контракты. Для SDK я бы описал очередь и обработку повторов.')
  self.assertEqual(self.cleaner()('SDK не проектировал.',retry),retry.return_value);retry.assert_called_once()
 def test_bad_rewrites_are_bounded_and_never_returned(self):
  retry=Mock(return_value='Нет отдельного подтверждённого проекта.')
  with self.assertRaises(NeedsDecision):self.cleaner()('Visio не применял.',retry)
  self.assertEqual(retry.call_count,2)
 def test_fact_and_policy_blocks_are_separate(self):
  p={'name':'Егор','screening_answers':'БКС: Claude.','screening_guidance':'Не приписывать production-внедрение агентов.','resume_text':'Рабочий опыт'}
  prompt=build_system_prompt(p,screening=True);facts=prompt.split('Личные условия:\n')[1].split('\nОпыт и навыки:')[0]
  self.assertEqual(json.loads(facts)['screening_answers'],'БКС: Claude.');self.assertNotIn('production',facts);self.assertIn(p['screening_guidance'],prompt.split('Внутренние правила:')[1])
 def test_profile_facts_models_and_explicit_limits_preserved(self):
  p=load_profile();facts=p['screening_answers']
  for word in ['Claude','GPT','Gemini','BI-инструменты не использовал','4 года 6 месяцев']:self.assertIn(word,facts)
  for word in ['не заданы','не подтверждены','Не заявлять','не придумывать']:self.assertNotIn(word,facts)
  updated=update_profile(p,{'screening_answers':facts});self.assertEqual(updated['screening_guidance'],p['screening_guidance']);self.assertEqual(updated['excluded_employers'],p['excluded_employers'])

if __name__=='__main__':unittest.main()
