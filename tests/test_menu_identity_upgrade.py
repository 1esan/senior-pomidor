import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import interview_catalog as c

def item(vid,description):return {'id':str(vid),'name':'Системный аналитик','employer_id':'3529','company':'СБЕР','negotiation_id':'n'+str(vid),'description':description}
def response(text,status=200,location=None):
 r=Mock(status_code=status,headers={'Location':location} if location else {});r.iter_content.return_value=[text.encode()];return r

class IdentityUpgradeTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)
  self.summary='Системный аналитик. Проектирование мультиагентной системы поддержки, создание AI-агентов, анализ и оптимизация процессов.'
  self.first=item(1,'Проектирование мультиагентной системы поддержки: сценарии маршрутизации задач. Участие в создании AI-агентов. Анализ и оптимизация процессов службы поддержки.')
  self.other=item(2,'Сбор требований к системе. Анализ и оптимизация процессов банка. SQL и Kafka.')
  self.entry={'title':'Системный аналитик','text':self.summary,'links':[],'label':'1. Системный аналитик','number':'1'}
 def test_short_unique_anchor_and_separate_corrobation(self):self.assertEqual(c.summary_match(self.summary,[self.first,self.other])['id'],'1')
 def test_duplicate_descriptions_are_ambiguous(self):self.assertIsNone(c.summary_match(self.summary,[self.first,item(3,self.first['description'])]))
 def test_generic_shared_words_are_insufficient(self):self.assertIsNone(c.summary_match('Системный аналитик. Анализ и оптимизация процессов банка.',[self.first,self.other]))
 def test_unique_anchor_alone_is_insufficient(self):self.assertIsNone(c.summary_match('Системный аналитик. Проектирование мультиагентной системы поддержки.',[self.first,self.other]))
 def test_renumbering_does_not_change_binding(self):
  c.remember_entry(self.base,self.entry,self.first,'summary_unique_description');changed={**self.entry,'number':'4','label':'4. Системный аналитик'}
  self.assertEqual(c.known_entry(self.base,changed,[self.first,self.other])['id'],'1')
 def test_changed_content_or_url_does_not_reuse_binding(self):
  c.remember_entry(self.base,self.entry,self.first,'summary_unique_description')
  self.assertIsNone(c.known_entry(self.base,{**self.entry,'text':'Другая команда'},[self.first]))
  self.assertIsNone(c.known_entry(self.base,{**self.entry,'links':['https://www.rabota.ru/vacancy/999/']},[self.first]))
 def test_changed_hh_description_employer_or_negotiation_invalidates(self):
  c.remember_entry(self.base,self.entry,self.first,'summary_unique_description')
  for changed in [{'description':'Другой проект'},{'employer_id':'wrong'},{'negotiation_id':'new-application'}]:
   self.assertIsNone(c.known_entry(self.base,self.entry,[{**self.first,**changed}]))
 def test_new_duplicate_candidate_invalidates_summary_proof(self):
  c.remember_entry(self.base,self.entry,self.first,'summary_unique_description')
  self.assertIsNone(c.known_entry(self.base,self.entry,[self.first,item(3,self.first['description'])]))
 def test_rabota_is_namespaced_and_strict(self):
  self.assertEqual(c.public_vacancy_key('https://www.rabota.ru/vacancy/123/'),'rabota:123');self.assertEqual(c.public_vacancy_key('https://rabota.ru/vacancy/123'),'rabota:123')
  self.assertNotEqual(c.public_vacancy_key('https://rabota.sber.ru/search/123'),'rabota:123')
  for url in ['http://www.rabota.ru/vacancy/123','https://www.rabota.ru.evil.test/vacancy/123','https://user:pass@rabota.ru/vacancy/123','https://rabota.ru:444/vacancy/123','https://127.0.0.1/vacancy/123']:
   self.assertIsNone(c.public_vacancy_key(url))
 def test_rabota_canonical_redirect_and_structured_description(self):
  c.PUBLIC_CACHE.clear();session=Mock();session.get.side_effect=[response('',302,'https://www.rabota.ru/vacancy/123/'),response('<script type="application/ld+json">'+json.dumps({'@type':'JobPosting','description':'<p>Уникальное описание вакансии</p>'})+'</script>')]
  with patch.object(c.requests,'Session',return_value=session):text=c.public_text('https://rabota.ru/vacancy/123')
  self.assertIn('Уникальное описание вакансии',text);self.assertEqual(session.get.call_count,2)
 def test_rabota_redirect_to_other_job_or_site_is_blocked(self):
  for location in ['https://www.rabota.ru/vacancy/999/','https://evil.test/vacancy/123/','https://rabota.sber.ru/search/123']:
   c.PUBLIC_CACHE.clear();session=Mock();session.get.return_value=response('',302,location)
   with patch.object(c.requests,'Session',return_value=session):self.assertEqual(c.public_text('https://rabota.ru/vacancy/123'),'')
   self.assertEqual(session.get.call_count,1)
 def test_public_binding_does_not_depend_on_title(self):
  entry={**self.entry,'links':['https://www.rabota.ru/vacancy/123/']};c.remember_entry(self.base,entry,self.other,'audited_public_description')
  self.assertEqual(c.known_entry(self.base,entry,[self.first,self.other])['id'],'2')

if __name__=='__main__':unittest.main()
