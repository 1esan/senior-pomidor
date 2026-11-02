import ast,json,sys,unittest
from pathlib import Path
from unittest.mock import Mock
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
from candidate import build_system_prompt,reply_problem
from autonomous_runtime import NeedsDecision
from profile_editor import update_profile

class AnswerVoiceUpgradeTests(unittest.TestCase):
 def profile(self):return {'screening_answers':'Example BI Tool не использовал.\nExample Language A, Example Language B и Example Container Platform: нет опыта в тестовом примере.\nИИ: использовал Example AI Tool.\nExample Product Z не использовал.'}
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
  for text in ['Example Product Z не использовал.','BI не использовал.','Example Container Platform не использовал.']:
   with self.subTest(text=text):self.assertIsNone(reply_problem(text,self.profile()))
 def test_known_bi_negative_cannot_justify_unknown_visio_negative(self):
  self.assertIsNotNone(reply_problem('Visio и BI не использовал.',self.profile()))
 def test_technical_negation_is_not_a_personal_denial(self):
  self.assertIsNone(reply_problem('Идемпотентность не позволяет повторно выполнить операцию.',self.profile()))
 def test_transferable_experience_and_hypothetical_approach_allowed(self):
  self.assertIsNone(reply_problem('Мой основной опыт — финансовые backend-интеграции. Для SDK я бы описал каталог событий и версии контракта.',self.profile()))
 def test_rewrite_occurs_before_returning_text(self):
  retry=Mock(return_value='В Example Employer Alpha использовал Example AI Tool для ревью API-контрактов.')
  self.assertEqual(self.cleaner()('Конкретные модели и инструменты не назову.',retry),retry.return_value);retry.assert_called_once()
 def test_unknown_negative_triggers_rewrite(self):
  retry=Mock(return_value='В проектах прорабатывал событийные контракты. Для SDK я бы описал очередь и обработку повторов.')
  self.assertEqual(self.cleaner()('SDK не проектировал.',retry),retry.return_value);retry.assert_called_once()
 def test_bad_rewrites_are_bounded_and_never_returned(self):
  retry=Mock(return_value='Нет отдельного подтверждённого проекта.')
  with self.assertRaises(NeedsDecision):self.cleaner()('Visio не применял.',retry)
  self.assertEqual(retry.call_count,2)
 def test_fact_and_policy_blocks_are_separate(self):
  p={'name':'Example Candidate','screening_answers':'Example Project Alpha: Example AI Tool.','screening_guidance':'Не приписывать production-внедрение агентов.','resume_text':'Synthetic work history for the isolated prompt test.'}
  prompt=build_system_prompt(p,screening=True);facts=prompt.split('Личные условия:\n')[1].split('\nОпыт и навыки:')[0]
  self.assertEqual(json.loads(facts)['screening_answers'],'Example Project Alpha: Example AI Tool.');self.assertNotIn('production',facts);self.assertIn(p['screening_guidance'],prompt.split('Внутренние правила:')[1])
 def test_profile_facts_models_and_explicit_limits_preserved(self):
  facts='Example AI Tool, Example Model One, Example Model Two. Example BI Tool не использовал. Стаж: 2 года 3 месяца.'
  p={'profile_confirmed':True,'name':'Example Candidate','resume_text':'Synthetic profile text that is long enough for profile editor validation.','salary_min':100000,'salary_max':120000,'screening_answers':facts,'screening_guidance':'Synthetic internal guidance.','excluded_employers':[{'company':'Example Employer Alpha','aliases':['Example Employer Alpha'],'hh_ids':['990000001']}]}
  for word in ['Example AI Tool','Example Model One','Example Model Two','Example BI Tool не использовал','2 года 3 месяца']:self.assertIn(word,facts)
  for word in ['не заданы','не подтверждены','Не заявлять','не придумывать']:self.assertNotIn(word,facts)
  updated=update_profile(p,{'screening_answers':facts});self.assertEqual(updated['screening_guidance'],p['screening_guidance']);self.assertEqual(updated['excluded_employers'],p['excluded_employers'])

if __name__=='__main__':unittest.main()
