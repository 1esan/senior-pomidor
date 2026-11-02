import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conversation_statistics import collect, PEER

class ConversationTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)
 def put(self,name,value):
  p=self.base/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False));return p
 def state(self,**extra):
  d={'current':{'vacancy_id':'12','name':'Аналитик','intro_fingerprint':f'{PEER}:100:abc'},'actions':{},'completed_interviews':{}};d.update(extra);return d
 def test_empty_sources(self):
  d=collect(self.base);self.assertEqual(d['telegram']['completed'],0);self.assertEqual(d['hh']['rows'],[])
 def test_preview_and_backups_are_excluded(self):
  self.put('.state/telegram-progress/web-preview.json',self.state(actions={f'{PEER}:101:abc:text:x':'confirmed'}));self.put('.state/telegram-progress/web-live-backup.json',self.state())
  self.assertEqual(collect(self.base)['telegram']['rows'],[])
 def test_only_text_confirmations_count_and_duplicate_transports_deduplicate(self):
  s=self.state(actions={f'{PEER}:101:abc:text:x':'confirmed',f'{PEER}:102:abc:text:x':'submitted',f'{PEER}:103:abc:button-native:x':'confirmed','999:1:x:text:x':'confirmed'})
  for transport in ['web','telethon']:self.put(f'.state/telegram-progress/{transport}-live.json',s)
  d=collect(self.base)['telegram'];self.assertEqual(d['confirmed_answers'],1);self.assertEqual(d['uncertain_actions'],1);self.assertEqual(d['rows'][0]['confirmed_answers'],1)
 def test_legacy_completion_separate(self):
  self.put('.state/telegram-progress/web-live.json',self.state(completed_interviews={'hh:1':{'vacancy_id':'1','name':'Old','legacy_identity_unverified':True},'hh:2':{'vacancy_id':'2','name':'New','intro_fingerprint':f'{PEER}:50:a','completed_at':123}}))
  d=collect(self.base)['telegram'];self.assertEqual(d['completed'],1);self.assertEqual(d['legacy_completed'],1);self.assertEqual(next(r for r in d['rows'] if r['vacancy_id']=='1')['status'],'legacy_review')
 def test_question_ranges_attribute_answers(self):
  self.put('.state/telegram-progress/web-live.json',self.state(actions={f'{PEER}:51:abc:text:x':'confirmed',f'{PEER}:101:abc:text:x':'confirmed'},completed_interviews={'hh:2':{'vacancy_id':'2','name':'Other','intro_fingerprint':f'{PEER}:50:a','completed_at':123}}))
  rows=collect(self.base)['telegram']['rows'];self.assertEqual({r['vacancy_id']:r['confirmed_answers'] for r in rows},{'2':1,'12':1})
 def test_memory_never_leaks_into_other_interview(self):
  self.put('.state/telegram-progress/web-live.json',self.state(active_context={'key':'hh:999','messages':[{'role':'assistant','content':'wrong'}]}))
  self.assertEqual(collect(self.base)['telegram']['rows'][0]['last_answer'],'')
 def test_real_reply_delay_runtime(self):
  self.put('.state/telegram-progress/web-live.json',self.state());self.put('.state/giga-autonomous.json',{'job_id':'a','pid':1,'vacancy_id':'12','phase':'reply_delay','updated_at':100,'send_after':120});self.put('.state/jobs/a.json',{'mode':'live','status':'running'})
  with patch('conversation_statistics.os.kill'):d=collect(self.base)['telegram']
  self.assertTrue(d['live']);self.assertEqual(d['rows'][0]['status'],'reply_delay')
 def test_dead_process_cannot_be_reported_as_running(self):
  self.put('.state/telegram-progress/web-live.json',self.state());self.put('.state/giga-autonomous.json',{'job_id':'a','pid':1,'vacancy_id':'12','phase':'generating'});self.put('.state/jobs/a.json',{'mode':'live','status':'running'})
  with patch('conversation_statistics.os.kill',side_effect=ProcessLookupError):d=collect(self.base)['telegram']
  self.assertFalse(d['live']);self.assertEqual(d['rows'][0]['status'],'paused')
 def test_observed_latency_excludes_attempt_only_and_deduplicates(self):
  p=self.base/'logs/giga-bot.log';p.parent.mkdir();p.write_text(f'2026-10-15 12:00:00,000 INFO BOT peer_id={PEER} [101]: Вопрос\n2026-10-15 12:00:30,000 INFO TELEGRAM_ATTEMPT: peer_id={PEER} question={PEER}:101:abc | Ответ\n2026-10-15 12:00:31,000 INFO TELEGRAM_SUBMITTED: peer_id={PEER}\n2026-10-15 12:00:32,000 INFO TELEGRAM_CONFIRMED: peer_id={PEER}\n2026-10-15 12:00:33,000 INFO TELEGRAM_CONFIRMED: peer_id={PEER}\n')
  d=collect(self.base)['telegram'];self.assertEqual(d['mean_response_seconds'],32);self.assertEqual(d['timing_samples'],1)
 def test_hh_snapshot_freshness_and_waiting(self):
  self.put('hh-data.json',{'generated_at':'2026-10-15T10:00:00Z','rows':[{'id':'1','state':'response','msgs_employer':2,'msgs_applicant':1,'unanswered':True},{'id':'2','state':'discard','msgs_employer':1,'unanswered':True}]})
  d=collect(self.base)['hh'];self.assertEqual(d['waiting_us'],1);self.assertEqual(d['generated_at'],'2026-10-15T10:00:00Z')

if __name__=='__main__':unittest.main()
