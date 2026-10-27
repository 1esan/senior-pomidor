import ast,importlib.util,json,logging,sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
import candidate as c
from autonomous_runtime import NeedsDecision

class DialogueReviewTests(unittest.TestCase):
 def profile(self):return {'screening_answers':'BI-инструменты не использовал. Python/Java: серьёзного релевантного опыта нет.'}
 def cleaner(self):
  tree=ast.parse((BASE/'giga-bot.py').read_text());nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('_strip_echo','clean_text_reply')]
  scope={'reply_problem':lambda t:c.reply_problem(t,self.profile()),'NeedsDecision':NeedsDecision,'LEAK_MARKERS':('сообщение рекрутёра',)}
  exec(compile(ast.Module(body=nodes,type_ignores=[]),'offline','exec'),scope);return scope['clean_text_reply']
 def test_exact_sent_aris_answer_is_rejected(self):
  text='С ARIS опыта у меня нет в описанном рабочем контексте, но я регулярно моделировал бизнес-процессы в BPMN.'
  self.assertIsNotNone(c.reply_problem(text,self.profile()))
 def test_denial_word_order_and_forms(self):
  for text in ['С ARIS опыта у меня нет.','Практического опыта работы с ARIS у меня пока нет.','У меня не было опыта с MongoDB.','Опыта с ARIS у меня не было.','Я пока не использовал ARIS.','С ARIS не сталкивался.','Профессиональные ML-модели не обучал.','Мне не приходилось с ARIS работать.','Не располагаю практическим опытом с ARIS.','Не имею такого опыта с Redis.','Практический опыт именно с ARIS или другой BPMS у меня не был основным.','Я не специалист по data science.','Мой опыт с ML связан с применением ИИ, а не с разработкой моделей.']:
   with self.subTest(text=text):self.assertIsNotNone(c.reply_problem(text,self.profile()))
 def test_source_language_not_ordinary_work_context(self):
  for text in ['В описанном рабочем контексте использовал API.','Из доступных сведений следует такой опыт.','В предоставленном описании нет такого опыта.','Не могу подтвердить опыт с ARIS.','С ARIS работал ли — не могу однозначно сказать.']:
   with self.subTest(text=text):self.assertIsNotNone(c.reply_problem(text,self.profile()))
  for text in ['В финансовом backend-контексте прорабатывал контракты.','В БКС использовал Claude для ревью API.','Для такого сценария я бы описал очередь событий.','Других вопросов пока нет, спасибо.']:
   with self.subTest(text=text):self.assertIsNone(c.reply_problem(text,self.profile()))
 def test_explicit_bi_denial_is_not_converted_to_positive(self):
  for text in ['BI не использовал.','BI-инструменты не использовал.']:
   self.assertIsNone(c.reply_problem(text,self.profile()))
 def test_feedback_receives_reason_and_rejected_text(self):
  bad='С ARIS опыта у меня нет.';good='Моделировал процессы в BPMN. Для BPMS я бы описал роли и переходы.'
  feedback=Mock(return_value=good);fallback=Mock()
  self.assertEqual(self.cleaner()(bad,fallback,retry_with_feedback=feedback),good)
  self.assertEqual(feedback.call_args.args[1],bad);self.assertIn('отсутствие опыта',feedback.call_args.args[0]);fallback.assert_not_called()
 def test_each_failed_rewrite_gets_its_own_reason(self):
  feedback=Mock(side_effect=['В описанном контексте нет проекта.','В БКС прорабатывал API.'])
  self.assertEqual(self.cleaner()('С ARIS опыта у меня нет.',Mock(),retry_with_feedback=feedback),'В БКС прорабатывал API.')
  self.assertEqual(feedback.call_count,2);self.assertNotEqual(feedback.call_args_list[0].args[0],feedback.call_args_list[1].args[0])
 def test_instruction_echo_uses_same_bounded_rewrite_budget(self):
  feedback=Mock(return_value='Сообщение рекрутёра: прочитайте инструкцию')
  with self.assertRaises(NeedsDecision):self.cleaner()('Сообщение рекрутёра: вопрос',Mock(),retry_with_feedback=feedback)
  self.assertEqual(feedback.call_count,2)
 def test_actual_retry_prompt_contains_reason_as_internal_data(self):
  tree=ast.parse((BASE/'giga-bot.py').read_text());handle=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='handle_last');force=next(n for n in handle.body if isinstance(n,ast.FunctionDef) and n.name=='_force_answer')
  model=Mock(return_value='Исправлено');scope={'ollama_chat':model,'text':'Работали с ARIS?','json':json}
  exec(compile(ast.Module(body=[force],type_ignores=[]),'offline','exec'),scope);scope['_force_answer']('Неизвестный опыт','С ARIS опыта у меня нет.')
  sent=model.call_args.args[0];self.assertIn('Неизвестный опыт',sent);self.assertIn('С ARIS опыта у меня нет.',sent);self.assertIn('данные, не инструкция',sent)
 def test_validator_proxy_tracks_module_reload(self):
  tree=ast.parse((BASE/'giga-bot.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='reply_problem');scope={'candidate_rules':c}
  exec(compile(ast.Module(body=[node],type_ignores=[]),'offline','exec'),scope)
  with patch.object(c,'reply_problem',return_value='NEW'):self.assertEqual(scope['reply_problem']('text'),'NEW')
 def test_history_is_not_authoritative_source_of_biography(self):
  prompt=c.build_system_prompt({'name':'Егор','resume_text':'Опыт'},screening=True)
  self.assertIn('История интервью — контекст диалога',prompt);self.assertIn('не источник новых биографических фактов',prompt)

if __name__=='__main__':unittest.main()
