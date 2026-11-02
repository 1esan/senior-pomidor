import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import interview_catalog as c
from telegram_web_guard import TARGET_PEER

def response(status=200,text='',location=None):
 r=Mock(status_code=status,headers={} if location is None else {'Location':location});r.iter_content.return_value=[text.encode()];return r

def item(vid):
 return {'id':str(vid),'name':'Системный аналитик','employer_id':'3529','company':'СБЕР','description':' '.join('уникальный'+str(vid)+'слово'+str(i) for i in range(40))}

class RedirectTests(unittest.TestCase):
 def setUp(self):c.PUBLIC_CACHE.clear()
 def fetch(self,responses,url='https://rabota.sber.ru/search/123'):
  session=Mock();session.get.side_effect=responses
  with patch.object(c.requests,'Session',return_value=session):result=c.public_text(url)
  return result,session
 def test_two_redirects_same_id_and_body(self):
  results=[response(308,location='/search/123/'),response(307,location='/search/sistemnyy-analitik-123/'),response(text='<h1>Аналитик</h1><p>Описание</p>')]
  text,s=self.fetch(results);self.assertIn('Описание',text);self.assertEqual(s.get.call_count,3);self.assertTrue(all(not call.kwargs['allow_redirects'] for call in s.get.call_args_list));self.assertTrue(all(r.close.called for r in results));s.close.assert_called_once()
 def test_external_redirect_never_requested(self):
  for target in ['https://evil.test/search/123','http://rabota.sber.ru/search/123','https://rabota.sber.ru.evil.test/search/123','https://user:pass@rabota.sber.ru/search/123']:
   with self.subTest(target=target):
    c.PUBLIC_CACHE.clear();text,s=self.fetch([response(302,location=target)]);self.assertEqual(text,'');self.assertEqual(s.get.call_count,1)
 def test_redirect_to_different_vacancy_rejected(self):
  text,s=self.fetch([response(307,location='/search/999/')]);self.assertEqual(text,'');self.assertEqual(s.get.call_count,1)
 def test_redirect_loop_is_bounded(self):
  text,s=self.fetch([response(308,location='/search/123/') ,response(307,location='/search/123')]);self.assertEqual(text,'');self.assertEqual(s.get.call_count,2)
 def test_failed_page_is_not_cached(self):
  text,_=self.fetch([response(503)]);self.assertEqual(text,'')
  text,s=self.fetch([response(text='<p>Восстановлено</p>')]);self.assertIn('Восстановлено',text);self.assertEqual(s.get.call_count,1)
 def test_success_is_cached(self):
  self.fetch([response(text='<p>Описание</p>')]);text,s=self.fetch([]);self.assertIn('Описание',text);s.get.assert_not_called()
 def test_oversize_page_rejected(self):
  text,_=self.fetch([response(text='a'*2000001)]);self.assertEqual(text,'')

class MenuLinkTests(unittest.TestCase):
 def menu(self):
  return {'mid':'449','peer_id':TARGET_PEER,'text':'По какой из них продолжить?\n\n'+'\n\n'.join(str(i)+'. Системный аналитик\nКраткое описание '+str(i) for i in range(1,5)),'buttons':[str(i)+'. Системный аналитик' for i in range(1,5)],'section_links':{str(i):['https://rabota.sber.ru/search/'+str(i*100)] for i in range(1,5)}}
 def test_four_equal_titles_resolve_and_persist_by_individual_links(self):
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);items=[item(i) for i in range(1,9)];menu=self.menu()
   fetch=Mock(side_effect=lambda url:items[int(c.official_id(url))//100-1]['description'])
   scope,label,unknown=c.select_entry(base,menu,{}, {'items':items},fetch=fetch)
   self.assertEqual(scope['id'],'1');self.assertEqual(label,'1. Системный аналитик');self.assertEqual(unknown,[])
   self.assertEqual(len(json.loads((base/'.state/giga-menu-links.json').read_text())),4)
   # A later menu reorders and renumbers rows. Its URL, not the old number, identifies the job.
   menu['section_links']={'1':['https://rabota.sber.ru/search/400'],'2':['https://rabota.sber.ru/search/300'],'3':['https://rabota.sber.ru/search/200'],'4':['https://rabota.sber.ru/search/100']}
   scope,label,_=c.select_entry(base,menu,{'completed_interviews':{'hh:4':{}}},{'items':items},fetch=Mock(side_effect=AssertionError('Must use saved proof')))
   self.assertEqual(scope['id'],'3');self.assertEqual(label,'2. Системный аналитик')
 def test_changed_hh_description_invalidates_saved_binding(self):
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);items=[item(i) for i in range(1,5)];menu=self.menu()
   c.select_entry(base,menu,{}, {'items':items},fetch=lambda url:items[int(c.official_id(url))//100-1]['description'])
   items[0]['description']='Изменившееся описание'
   completed={'completed_interviews':{'hh:2':{},'hh:3':{},'hh:4':{}}}
   scope,_,unknown=c.select_entry(base,menu,completed,{'items':items},fetch=lambda url:'')
   self.assertIsNone(scope);self.assertTrue(unknown)
 def test_learned_binding_cannot_add_missing_invitation_or_change_employer(self):
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);items=[item(i) for i in range(1,5)]
   c.select_entry(base,self.menu(),{}, {'items':items},fetch=lambda url:items[int(c.official_id(url))//100-1]['description'])
   self.assertEqual(c.learned_candidates(base,[]),[])
   changed={**items[0],'employer_id':'other'}
   self.assertEqual(c.learned_candidates(base,[changed])[0]['official_ids'],[])
 def test_short_menu_summary_never_guesses_generic_title(self):
  with tempfile.TemporaryDirectory() as td:
   scope,_,unknown=c.select_entry(Path(td),self.menu(),{}, {'items':[item(i) for i in range(1,9)]},fetch=lambda url:'')
   self.assertIsNone(scope);self.assertEqual(len(unknown),4)

if __name__=='__main__':unittest.main()
