import sys,unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vacancy_policy import entry_level_reason,application_decision
class EntryLevelTests(unittest.TestCase):
 def test_excluded_titles(self):
  for title in ['Младший системный аналитик','Начинающий аналитик','Аналитик-стажёр','Стажер аналитик','Стажировка в аналитике','Junior System Analyst','JUNIOR/Middle аналитик','Jr. analyst','Analyst (intern)','Internship analyst','Trainee analyst','Graduate analyst','Entry-level analyst','Entry level analyst','Джун аналитик','Джуниор аналитик','Молодой специалист — аналитик','Системный аналитик без опыта','Младший специалист','Начинающая аналитик','Системный аналитик (ученик)','Ученик системного аналитика','Ученица аналитика','Вакансия для ученика аналитика','Аналитик — ученическая позиция','Apprentice system analyst','System analyst apprenticeship']:
   with self.subTest(title=title):
    self.assertIsNotNone(entry_level_reason({'name':title}))
    with patch('vacancy_policy.contact_reason',return_value=None):self.assertEqual(application_decision({'name':title},{})[0],'skip')
 def test_relevant_titles_and_description_not_excluded(self):
  for title in ['Системный аналитик','Middle System Analyst','Ведущий аналитик','Senior analyst','Fullstack аналитик','Бизнес-системный аналитик','Аналитик стажа и выплат','Internal systems analyst','Аналитик JRuby','Аналитик обучающих систем']:
   with self.subTest(title=title):
    vacancy={'name':title,'description':'Наставничество: junior, стажёры, начинающие сотрудники, ученики и apprentice. Можно без опыта.'}
    self.assertIsNone(entry_level_reason(vacancy))
    with patch('vacancy_policy.contact_reason',return_value=None):self.assertEqual(application_decision(vacancy,{})[0],'allow')
 def test_bans_preserved(self):
  with patch('vacancy_policy.contact_reason',return_value='Запрещённая компания'):self.assertEqual(application_decision({'name':'Senior аналитик'},{}),('skip','Запрещённая компания'))
 def test_reason_names_trigger_and_title(self):
  reason=entry_level_reason({'name':'Младший системный аналитик'})
  self.assertIn('Младший',reason);self.assertIn('Младший системный аналитик',reason)
if __name__ == '__main__':unittest.main()
