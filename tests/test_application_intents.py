import copy,contextlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from application_intents import blocks_application
import hh

def released():
 return {'status':'retry_allowed','reconciliation':{'result':'not_sent','reason':'explicit_captcha_rejection_and_no_negotiation','http_status':403,'response_kind':'captcha','negotiations_checked':['active','archived'],'checked_at':'2026-10-28T00:00:00Z'}}

class IntentTests(unittest.TestCase):
 def test_uncertain_and_confirmed_outcomes_remain_blocked(self):
  for record in [None,{}, {'status':'attempting'},{'status':'sent'},{'status':'retry_allowed'},{'status':'retry_allowed','reconciliation':{'result':'not_sent'}}]:
   with self.subTest(record=record):self.assertTrue(blocks_application(record))
 def test_only_explicit_rejection_with_complete_reconciliation_released(self):
  good=released();self.assertFalse(blocks_application(good))
  for key,value in [('result','unknown'),('http_status',502),('response_kind','network_unknown'),('negotiations_checked',['active']),('checked_at',None)]:
   bad=copy.deepcopy(good);bad['reconciliation'][key]=value
   with self.subTest(key=key):self.assertTrue(blocks_application(bad))
 def test_wrapper_rechecks_existing_intent_before_replacing_it(self):
  for original in [released(),{'status':'attempting'},{'status':'sent'},None]:
   with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);cfg=root/'hh';cfg.mkdir();path=cfg/'application-intents.json';path.write_text(json.dumps({'12':original}))
    tool=SimpleNamespace(api_client=SimpleNamespace(captcha_handler=None,max_retries=1))
    def run(cmd):
     v={'id':'12','employer':{'name':'Example'}}
     decision,_=tool.candidate_vacancy_policy(v)
     if isinstance(original,dict) and original.get('status')=='retry_allowed':
      self.assertEqual(decision,'allow');self.assertEqual(tool.candidate_vacancy_policy(v)[0],'allow')
      tool.application_intent(v,{'resume_id':'r','message':'test'})
      with self.assertRaises(RuntimeError):tool.application_intent(v,{'resume_id':'r','message':'test'})
      tool.application_result(v,'test',False)
     else:
      self.assertEqual(decision,'skip')
      with self.assertRaises(RuntimeError):tool.application_intent(v,{'resume_id':'r','message':'test'})
     return 0
    tool.run=run
    with patch.object(hh,'BASE',root),patch.object(hh,'HH_CONFIG',cfg),patch.object(hh,'load_profile',return_value={}),patch.object(hh,'build_command',return_value=['apply']),patch.object(hh,'hh_tool',return_value=tool),patch.object(hh,'application_decision',return_value=('allow','ok')),patch.object(hh,'operation_lock',return_value=contextlib.nullcontext()):
     self.assertEqual(hh.run(hh.parser().parse_args(['apply','--live'])),0)
    after=json.loads(path.read_text())['12']
    if isinstance(original,dict) and original.get('status')=='retry_allowed':
     self.assertEqual(after['status'],'sent');self.assertIn('previous_reconciliation',after)
    else:self.assertEqual(after,original)
if __name__=='__main__':unittest.main()
