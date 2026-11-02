"""Navigation within the bound bot is allowed; recipient changes remain latched."""
import logging,os,sys,time,unittest
from pathlib import Path
from unittest.mock import patch
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE));os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(BASE/'.browsers')
from playwright.async_api import async_playwright
import telegram_web_guard as guard
from autonomous_runtime import NeedsDecision
HTML=f'''<div class="chat"><div class="bubbles"><div class="bubble is-in" data-mid="1"><div class="message">Вопрос</div></div></div><div class="input-message-input" contenteditable="true" data-peer-id="{guard.TARGET_PEER}"></div><button class="btn-send send">Send</button></div><script>window.sent=[];document.querySelector('button').onclick=()=>sent.push(document.querySelector('.input-message-input').innerText);</script>'''
class NavigationTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.runtime=await async_playwright().start();self.browser=await self.runtime.chromium.launch(headless=True,channel='chromium');self.context=await self.browser.new_context();await self.context.set_offline(True)
  await self.context.route('https://web.telegram.org/**',lambda route:route.fulfill(status=200,content_type='text/html; charset=utf-8',body=HTML))
  self.page=await self.context.new_page();await self.page.goto('https://web.telegram.org/k/#@Giga_recruiter_bot');await guard.bind_page(self.page,time.time()+120)
 async def asyncTearDown(self):await self.browser.close();await self.runtime.stop()
 async def test_same_route_popstate_allows_scoped_dispatch(self):
  await self.page.evaluate("() => window.dispatchEvent(new PopStateEvent('popstate',{state:{scroll:10}}))")
  self.assertEqual(await guard.assert_target(self.page),guard.TARGET_PEER)
  await self.page.locator('.input-message-input').fill('Ответ')
  await guard.dispatch(self.page,guard.SEND_JS,{'text':'Ответ','mid':'1','source_text':'Вопрос'})
  self.assertEqual(await self.page.evaluate('sent'),['Ответ'])
 async def test_username_to_same_numeric_peer_remains_valid(self):
  await self.page.evaluate(f"() => {{const oldURL=location.href;history.replaceState(null,'','#{guard.TARGET_PEER}');window.dispatchEvent(new HashChangeEvent('hashchange',{{oldURL,newURL:location.href}}));}}")
  self.assertEqual(await guard.assert_target(self.page),guard.TARGET_PEER)
 async def test_foreign_route_blocks_even_if_dom_still_old_bot(self):
  await self.page.evaluate("() => {history.pushState(null,'','#123');window.dispatchEvent(new PopStateEvent('popstate'));}")
  with self.assertRaises(NeedsDecision):await guard.assert_target(self.page)
  self.assertEqual(await self.page.evaluate('sent'),[])
 async def test_fast_route_out_and_back_stays_latched(self):
  await self.page.evaluate("""() => {const initial=location.href;history.replaceState(null,'','#123');const foreign=location.href;history.replaceState(null,'','#@Giga_recruiter_bot');window.dispatchEvent(new HashChangeEvent('hashchange',{oldURL:initial,newURL:foreign}));window.dispatchEvent(new HashChangeEvent('hashchange',{oldURL:foreign,newURL:location.href}));}""")
  with self.assertRaises(NeedsDecision):await guard.assert_target(self.page)
 async def test_same_route_event_never_clears_foreign_peer_latch(self):
  await self.page.evaluate(f"() => {{const editor=document.querySelector('.input-message-input');editor.dataset.peerId='123';editor.dataset.peerId='{guard.TARGET_PEER}';}}")
  await self.page.evaluate("() => window.dispatchEvent(new PopStateEvent('popstate'))")
  with self.assertRaises(NeedsDecision):await guard.assert_target(self.page)
 async def test_foreign_peer_on_same_route_is_blocked(self):
  await self.page.evaluate("() => {document.querySelector('.input-message-input').dataset.peerId='123';window.dispatchEvent(new PopStateEvent('popstate'));}")
  with self.assertRaises(NeedsDecision):await guard.assert_target(self.page)
 async def test_pushstate_foreign_route_is_checked_without_event(self):
  await self.page.evaluate("() => history.pushState(null,'','#123')")
  with self.assertRaises(NeedsDecision):await guard.assert_target(self.page)
 async def test_missing_composer_is_not_treated_as_safe_navigation(self):
  await self.page.evaluate("() => {document.querySelector('.input-message-input').remove();window.dispatchEvent(new PopStateEvent('popstate'));}")
  with self.assertRaises(NeedsDecision):await guard.assert_target(self.page)
 async def test_diagnostics_are_once_and_do_not_log_query_secrets(self):
  await self.page.evaluate("() => {history.replaceState(null,'','?token=secret-value#@Giga_recruiter_bot');window.dispatchEvent(new PopStateEvent('popstate'));}")
  with self.assertLogs('telegram-guard',level='INFO') as captured:await guard.assert_target(self.page)
  self.assertEqual(len(captured.output),1);self.assertNotIn('secret-value',captured.output[0]);self.assertIn('peer_before',captured.output[0]);self.assertIn('peer_after',captured.output[0])
  with patch.object(logging.getLogger('telegram-guard'),'info') as log:await guard.assert_target(self.page)
  log.assert_not_called()
if __name__=='__main__':unittest.main()
