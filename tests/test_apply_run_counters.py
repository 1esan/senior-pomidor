import json,tempfile,unittest
from pathlib import Path
from statistics_store import recent_application_runs
class ApplicationCountersTests(unittest.TestCase):
 def test_real_runs_only_and_deduplicate_sent(self):
  with tempfile.TemporaryDirectory() as t:
   base=Path(t);folder=base/'.state/runs';folder.mkdir(parents=True)
   cases=[('20261023-100000',{'action':'apply','mode':'live','results':[{'status':'sent','vacancy_id':'1'},{'status':'sent','vacancy_id':'1'},{'status':'preview','vacancy_id':'2'}]}),('20261023-110000',{'action':'apply','mode':'live','results':[{'status':'sent','vacancy_id':'3'},{'status':'sent','vacancy_id':'4'}],'tests':[{'status':'sent','vacancy_id':'4'}]}),('20261023-120000',{'action':'apply','mode':'preview','results':[{'status':'preview','vacancy_id':'5'}]}),('20261023-130000',{'action':'reply','mode':'live','results':[{'status':'sent','vacancy_id':'6'}]})]
   for name,data in cases:(folder/('hh-'+name+'.json')).write_text(json.dumps(data))
   self.assertEqual([x['sent'] for x in recent_application_runs(base)],[2,1])
 def test_running_or_failed_zero_is_still_latest_run(self):
  with tempfile.TemporaryDirectory() as t:
   base=Path(t);folder=base/'.state/runs';folder.mkdir(parents=True)
   p=folder/'hh-20261023-100000.json';p.write_text(json.dumps({'action':'apply','mode':'live','results':[]}))
   self.assertEqual(recent_application_runs(base)[0]['sent'],0)
   p.write_text(json.dumps({'action':'apply','mode':'live','results':[{'status':'sent','vacancy_id':'1'}]}))
   self.assertEqual(recent_application_runs(base)[0]['sent'],1)
 def test_empty_and_malformed(self):
  with tempfile.TemporaryDirectory() as t:
   self.assertEqual(recent_application_runs(t),[])
   folder=Path(t)/'.state/runs';folder.mkdir(parents=True);(folder/'hh-bad.json').write_text('{')
   self.assertEqual(recent_application_runs(t),[])
if __name__=='__main__':unittest.main()
