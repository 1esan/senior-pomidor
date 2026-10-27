import unittest,json
from unittest.mock import Mock,patch
import cover_letters as c

P={'phone':'+7 999 000-00-00','telegram':'@example_candidate','resume_text':'БКС: REST и Kafka',
   'screening_answers':'Стаж 4 года 6 месяцев.','city':'Москва','salary_min':280000}
D={'intro':'Заинтересовала ваша вакансия системного аналитика. В БКС работал над автоследованием.',
   'matches':[{'requirement':'REST API','evidence':'Если пройтись по основным требованиям: в БКС проектировал контракты API и обработку ошибок.'},
              {'requirement':'Kafka','evidence':'Прорабатывал повторные события и статусы исполнения.'}], 'answers':[]}

def raw(data):return json.dumps(data,ensure_ascii=False)

class CoverLettersTests(unittest.TestCase):
 def test_readable_prose_with_approved_greeting_and_contacts(self):
  letter=c.render(raw(D),P,{'motivation':'Проект перешёл в поддержку.'})
  self.assertTrue(letter.startswith('Доброго времени суток)\n\nЗаинтересовала'))
  self.assertIn('\n\nЕсли пройтись по основным требованиям вакансии:',letter)
  self.assertNotIn('По требованиям вакансии:',letter)
  self.assertNotIn('•',letter)
  self.assertNotIn('REST API:',letter)
  self.assertIn(P['phone'],letter)
  self.assertIn('https://t.me/example_candidate',letter)
  self.assertIn('или в ТГ: https://t.me/example_candidate',letter)
  self.assertNotIn('Telegram:',letter)
  self.assertEqual(letter.count('Если пройтись по основным требованиям'),1)
  self.assertTrue(letter.endswith('\n\nБуду рад пообщаться!'))
 def test_reason_and_salary_are_not_appended_without_request(self):
  letter=c.render(raw(D),P,{'motivation':'Проект перешёл в поддержку.'})
  self.assertNotIn('поддержку',letter)
  self.assertNotIn('Мотивация поиска',letter)
  self.assertNotIn('280',letter)
 def test_requested_numbered_answers_are_preserved(self):
  data={**D,'answers':['1. Ожидания: 280–320 тысяч рублей на руки.','2. Проживаю в Москве.']}
  letter=c.render(raw(data),P,{})
  self.assertIn('1. Ожидания: 280-320 тысяч рублей на руки.\n2. Проживаю в Москве.',letter)
 def test_long_dashes_cannot_reach_letter(self):
  data={**D,'intro':'Мой проект — автоследование, стаж – 4,5 года.'}
  letter=c.render(raw(data),P,{})
  self.assertNotIn('—',letter);self.assertNotIn('–',letter)
 def test_legacy_greeting_does_not_duplicate(self):
  data={**D,'intro':'Здравствуйте! В БКС работал над автоследованием.'}
  letter=c.render(raw(data),P,{})
  self.assertNotIn('Здравствуйте',letter)
  self.assertEqual(letter.count('Доброго времени суток)'),1)
 def test_invalid_and_service_answers_blocked(self):
  for value in ('plain',raw({'intro':'hello','matches':[]}),raw({**D,'matches':[{'requirement':'API','evidence':'Согласно предоставленному профилю, знаю API.'}]})):
   with self.subTest(value=value),self.assertRaises(c.CoverLetterNeedsReview):c.render(value,P,{})
 def test_source_omission_and_unknown_required_fact_blocked(self):
  for data in ({**D,'matches':[{'requirement':'SQL','evidence':'Конкретные задачи с оконными функциями в моём опыте не описаны.'}]},
               {**D,'answers':['NEEDS_USER']}, {**D,'answers':['Образование нужно уточнить отдельно.']}):
   with self.subTest(data=data),self.assertRaises(c.CoverLetterNeedsReview):c.render(raw(data),P,{})
 def test_bureaucracy_and_markdown_are_rejected(self):
  for text in ['Осуществлял подготовку документации.','Обладаю обширным опытом интеграций.','**Проектировал API**.','• Проектировал API.']:
   with self.subTest(text=text),self.assertRaises(c.CoverLetterNeedsReview):
    c.render(raw({**D,'matches':[{'requirement':'API','evidence':text}]}),P,{})
 def test_unasked_disclaimer_retries_but_explicit_negative_answer_is_allowed(self):
  profile={**P,'screening_answers':P['screening_answers']+' Депозитарным учетом не занимался.'}
  data={**D,'matches':[{'requirement':'Брокер','evidence':'Проектировал интеграции, но не вёл депозитарный учет.'}]}
  with self.assertRaises(c.CoverLetterNeedsReview):c.render(raw(data),profile,{})
  requested={**D,'answers':['Депозитарным учетом не занимался.']}
  self.assertIn('Депозитарным учетом не занимался.',c.render(raw(requested),profile,{}))
 def test_full_description_sources_and_personal_answers_used(self):
  with patch.object(c,'load_experience_context',return_value='Кейс легенды: инцидент Kafka') as source:
   result=json.loads(c.inputs(P,{'id':'1','name':'СА','description':'<p>Требования:</p><li>REST</li><li>Kafka</li>'}))
  self.assertIn('Кейс легенды',result['cases']);self.assertIn('Kafka',source.call_args.args[0])
  self.assertIn('\n',result['vacancy']['description'])
  self.assertEqual(result['candidate']['city'],'Москва')
  self.assertEqual(result['candidate']['salary_min'],280000)
  self.assertNotIn('phone',result['candidate'])
 def test_missing_description_blocks(self):
  with self.assertRaises(c.CoverLetterNeedsReview):c.inputs(P,{'id':'1'})
 def test_duplicate_requirements_block(self):
  with self.assertRaises(c.CoverLetterNeedsReview):c.render(raw({**D,'matches':[D['matches'][0]]*2}),P,{})
 def test_invalid_answers_block(self):
  for answers in ('Москва',[None],[''],['x']*11):
   with self.subTest(answers=answers),self.assertRaises(c.CoverLetterNeedsReview):c.render(raw({**D,'answers':answers}),P,{})
 def test_generation_fresh_history_and_retry(self):
  tool=Mock();tool.get_openai_args.return_value={'history':[{'role':'assistant','content':'Другой кандидат'}]}
  tool.get_ai_client.return_value.complete.side_effect=['broken',raw(D)]
  with patch.object(c,'inputs',return_value='Факты и вакансия'):
   letter=c.generate(tool,P,{'id':'1'})
  self.assertEqual(tool.get_ai_client.call_args.kwargs['history'],[])
  self.assertEqual(tool.get_ai_client.return_value.complete.call_count,2)
  self.assertTrue(letter.startswith('Доброго времени суток)'))
 def test_exhausted_retry_never_returns_bad_letter(self):
  tool=Mock();tool.get_openai_args.return_value={}
  tool.get_ai_client.return_value.complete.return_value='NEEDS_USER'
  with patch.object(c,'inputs',return_value='Факты и вакансия'),self.assertRaises(c.CoverLetterNeedsReview):
   c.generate(tool,P,{'id':'1'})

if __name__=='__main__':unittest.main()
