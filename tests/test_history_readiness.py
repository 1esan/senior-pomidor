"""History loading is independent of the visible Telegram composer."""
import importlib.util,logging,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
with patch('logging.FileHandler',return_value=logging.NullHandler()):
 spec=importlib.util.spec_from_file_location('history_engine',BASE/'giga-bot.py');engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)

class HistoryReadinessTests(unittest.IsolatedAsyncioTestCase):
 async def run_wait(self,snapshots,*,busy=None,timeout=6,stable=1):
  elapsed=[0.];calls=[0];epoch=engine.time.time()
  async def scrape(page):
   index=min(calls[0],len(snapshots)-1);calls[0]+=1;return snapshots[index]
  async def sleep(seconds):elapsed[0]+=seconds
  clock=SimpleNamespace(time=lambda:epoch+elapsed[0],monotonic=lambda:elapsed[0])
  page=None if busy is None else SimpleNamespace(evaluate=AsyncMock(side_effect=lambda script:busy.pop(0) if len(busy)>1 else busy[0]))
  engine.WEB_DEADLINE=epoch+100
  with patch.object(engine,'time',clock),patch.object(engine.asyncio,'sleep',new=sleep),patch.object(engine,'scrape',new=scrape),patch.object(engine,'run_status') as status,patch.dict(engine.CONFIG,history_load_timeout_seconds=timeout,history_stable_seconds=stable):
   result=await engine.wait_history(page)
  return result,elapsed[0],calls[0],status
 def message(self,mid,text):return {'mid':str(mid),'peer_id':engine.TARGET_PEER,'text':text,'buttons':[],'dir':'in'}
 async def test_empty_editor_stage_does_not_finish_preview(self):
  message=self.message(2,'Выберите вакансию')
  result,elapsed,calls,status=await self.run_wait([[],[],[message]])
  self.assertEqual(result,[message]);self.assertGreaterEqual(elapsed,2);self.assertGreaterEqual(calls,5)
  self.assertEqual(status.call_args.kwargs['phase'],'history_ready')
 async def test_partial_history_must_settle_after_change(self):
  old=self.message(1,'Старая часть истории');new=self.message(2,'Актуальное меню')
  result,elapsed,_,_=await self.run_wait([[old],[old],[new]])
  self.assertEqual(result,[new]);self.assertGreaterEqual(elapsed,2)
 async def test_busy_loader_does_not_count_as_stable_history(self):
  message=self.message(2,'Меню')
  result,elapsed,_,_=await self.run_wait([[message]],busy=[True,True,False])
  self.assertEqual(result,[message]);self.assertGreaterEqual(elapsed,2)
 async def test_timeout_is_a_pause_not_success_or_empty_chat_claim(self):
  with self.assertRaisesRegex(engine.NeedsDecision,'История Telegram не загрузилась'):
   await self.run_wait([[]],timeout=2)
 async def test_target_change_is_not_swallowed_as_loading(self):
  engine.WEB_DEADLINE=engine.time.time()+20
  with patch.object(engine,'scrape',new=AsyncMock(side_effect=engine.NeedsDecision('foreign peer'))),patch.object(engine,'run_status'):
   with self.assertRaisesRegex(engine.NeedsDecision,'foreign peer'):await engine.wait_history(None)
if __name__=='__main__':unittest.main()
