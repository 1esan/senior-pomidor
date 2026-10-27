import asyncio,importlib.util,time,unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
B=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('readiness_engine',B/'giga-bot.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_waits_through_unready_and_foreign_until_exact_peer(self):
        page=type('Page',(),{})();page.evaluate=AsyncMock(side_effect=[None,'123',m.TARGET_PEER])
        m.WEB_DEADLINE=time.time()+60
        with patch.object(m.asyncio,'sleep',new=AsyncMock()):
            self.assertTrue(await m.wait_login(page))
        self.assertEqual(page.evaluate.await_count,3)
    async def test_expired_session_cannot_become_ready(self):
        page=type('Page',(),{})();page.evaluate=AsyncMock(return_value=m.TARGET_PEER)
        m.WEB_DEADLINE=time.time()-1
        with self.assertRaises(m.NeedsDecision):await m.wait_login(page)
        page.evaluate.assert_not_called()
