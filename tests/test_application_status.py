import json,tempfile,unittest
from pathlib import Path
from application_status import publish_snapshot,enrich,normalise,journey

class ApplicationStatusTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)
 def item(self,nid='n1',vid='12',state='discard',created='2026-10-01T00:00:00Z'):
  return {'id':nid,'state':{'id':state},'created_at':created,'updated_at':'2026-10-16T00:00:00Z','vacancy':{'id':vid,'name':'Одинаковое название','alternate_url':'https://nn.hh.ru/vacancy/'+vid,'employer':{'id':'3529','name':'СБЕР'}}}
 def row(self,completed=True):
  return {'12':{'vacancy_id':'12','name':'Одинаковое название','company':'СБЕР','status':'completed' if completed else 'queued','confirmed_answers':0,'completed_at':20 if completed else None}}
 def result(self,rows,started=None):
  out=enrich(rows,self.base,started or set());return out,rows['12']
 def test_verified_completion_survives_rejection(self):
  publish_snapshot(self.base,[self.item()],30);rows=self.row();summary,r=self.result(rows)
  self.assertEqual(r['status'],'completed');self.assertEqual(r['application_outcome'],'rejected');self.assertEqual(r['interview_stage'],'completed');self.assertEqual(summary['counts']['completed_and_rejected'],1)
 def test_first_seen_rejection_does_not_invent_chronology(self):
  publish_snapshot(self.base,[self.item()],30);_,r=self.result(self.row());self.assertEqual(r['rejection_sequence'],'unknown');self.assertEqual(r['application_label'],'Отказ')
 def test_confirmed_rejection_after_interview_requires_later_non_rejection(self):
  publish_snapshot(self.base,[self.item(state='invitation')],25,observed_since=25);publish_snapshot(self.base,[self.item()],30);_,r=self.result(self.row())
  self.assertEqual(r['rejection_sequence'],'after_interview');self.assertEqual(r['application_label'],'Отказ после интервью')
 def test_rejection_before_completion(self):
  publish_snapshot(self.base,[self.item()],10);_,r=self.result(self.row());self.assertEqual(r['rejection_sequence'],'before_completion')
 def test_rejected_application_without_interview_is_added(self):
  publish_snapshot(self.base,[self.item()],30);rows={};summary=enrich(rows,self.base,set());self.assertEqual(rows['12']['interview_stage'],'not_started');self.assertEqual(summary['counts']['rejected_without_completion'],1)
 def test_user_withdrawal_is_not_employer_rejection(self):
  publish_snapshot(self.base,[self.item(state='discard_by_applicant')],30);summary,r=self.result(self.row(False));self.assertEqual(r['application_outcome'],'withdrawn');self.assertEqual(summary['counts']['rejected'],0)
 def test_same_name_different_ids_cannot_cross_link(self):
  publish_snapshot(self.base,[self.item(vid='13')],30);_,r=self.result(self.row());self.assertEqual(r['application_outcome'],'unknown')
 def test_new_application_supersedes_old_rejection(self):
  publish_snapshot(self.base,[self.item(),self.item(nid='n2',state='response',created='2026-10-15T00:00:00Z')],30);_,r=self.result(self.row());self.assertEqual(r['application_id'],'n2');self.assertEqual(r['application_outcome'],'pending')
 def test_old_snapshot_cannot_overwrite_fresh(self):
  publish_snapshot(self.base,[self.item()],30);publish_snapshot(self.base,[self.item(state='response')],10);_,r=self.result(self.row());self.assertEqual(r['application_outcome'],'rejected')
 def test_completed_interview_with_open_application_is_waiting(self):
  publish_snapshot(self.base,[self.item(state='invitation')],30);summary,r=self.result(self.row());self.assertEqual(summary['counts']['awaiting_outcome'],1)
 def test_in_progress_is_independent_from_hh_rejection(self):
  publish_snapshot(self.base,[self.item()],30);_,r=self.result(self.row(False),{'12'});self.assertEqual(r['interview_stage'],'in_progress');self.assertEqual(r['application_outcome'],'rejected')
 def test_long_snapshot_does_not_invent_after_interview_order(self):
  publish_snapshot(self.base,[self.item(state='invitation')],25,observed_since=10);publish_snapshot(self.base,[self.item()],30);_,r=self.result(self.row());self.assertEqual(r['rejection_sequence'],'unknown')
 def test_completed_is_not_downgraded_by_hh_invitation(self):
  publish_snapshot(self.base,[self.item(state='invitation')],30);_,r=self.result(self.row());self.assertEqual(r['journey_code'],'completed_waiting');self.assertEqual(r['journey_label'],'Интервью пройдено · ожидается обратная связь');self.assertEqual(r['application_state'],'invitation')
 def test_rejected_completed_has_terminal_combined_status(self):
  self.assertEqual(journey('completed','rejected',True),('rejected_completed','Отказ · интервью пройдено'))
 def test_rejected_unfinished_is_not_completed(self):
  self.assertEqual(journey('in_progress','rejected',True),('rejected_unfinished','Отказ · интервью не пройдено'))
 def test_telegram_invitation_must_be_known(self):
  self.assertEqual(journey('not_started','invited',False)[0],'applied');self.assertEqual(journey('not_started','invited',True)[0],'waiting_interview')
 def test_progress_independent_of_hh_generic_invitation(self):
  self.assertEqual(journey('in_progress','invited',True)[0],'interview_in_progress')
 def test_missing_hh_status_does_not_erase_completed_interview(self):
  summary,r=self.result(self.row());self.assertEqual(r['journey_code'],'completed_waiting');self.assertEqual(summary['counts']['awaiting_outcome'],1)
 def test_conflicting_identity_rejected(self):
  item=self.item();item['vacancy']['alternate_url']='https://hh.ru/vacancy/999'
  with self.assertRaises(ValueError):normalise(item)
 def test_external_urls_are_not_used_to_match(self):
  self.assertIsNone(normalise({'id':'x','vacancy_url':'https://example.com/vacancy/12','state':'discard'}))

if __name__=='__main__':unittest.main()
