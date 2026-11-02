import asyncio,os,sys,time,unittest
from pathlib import Path
from playwright.async_api import async_playwright
B=Path(__file__).resolve().parents[1];sys.path.insert(0,str(B))
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(B/'.browsers')
import telegram_web_guard as g
from autonomous_runtime import NeedsDecision
from telegram_state import fingerprint
from candidate import reply_problem
HTML=f'''<div class="chat"><div class="bubbles"><div class="bubble is-in" data-mid="1"><div class="message">Вопрос</div><button class="reply-markup-button">Да</button></div></div><div class="input-message-input" contenteditable="true" data-peer-id="{g.TARGET_PEER}"></div><button class="btn-send send">Send</button></div><script>window.sent=[];document.querySelector('.btn-send').onclick=()=>sent.push(document.querySelector('.input-message-input').innerText);document.querySelector('.reply-markup-button').onclick=()=>sent.push('button');</script>'''
class RecipientSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.p=await async_playwright().start();self.browser=await self.p.chromium.launch(headless=True,channel='chromium')
        self.context=await self.browser.new_context();await self.context.set_offline(True)
        self.page=await self.context.new_page();await self.page.set_content(HTML);await g.bind_page(self.page,time.time()+120)
    async def asyncTearDown(self):
        await self.browser.close();await self.p.stop()
    async def prepared(self):
        await self.page.locator('.input-message-input').fill('Ответ');return {'text':'Ответ','mid':'1','source_text':'Вопрос'}
    async def test_valid_peer_dispatches_only_scoped_button(self):
        await g.dispatch(self.page,g.SEND_JS,await self.prepared());self.assertEqual(await self.page.evaluate('sent'),['Ответ'])
    async def test_wrong_chat_before_fill_blocks(self):
        await self.page.evaluate("document.querySelector('.input-message-input').dataset.peerId='123'")
        with self.assertRaises(NeedsDecision):await g.assert_target(self.page)
        self.assertEqual(await self.page.evaluate('sent'),[])
    async def test_switch_while_generating_then_back_stays_blocked(self):
        await self.page.evaluate("document.querySelector('.input-message-input').dataset.peerId='123'")
        await self.page.evaluate(f"document.querySelector('.input-message-input').dataset.peerId='{g.TARGET_PEER}'")
        with self.assertRaises(NeedsDecision):await g.dispatch(self.page,g.SEND_JS,await self.prepared())
        self.assertEqual(await self.page.evaluate('sent'),[])
    async def test_fast_switch_out_and_back_in_one_task_latches(self):
        arg=await self.prepared()
        await self.page.evaluate(f"const e=document.querySelector('.input-message-input');e.dataset.peerId='123';e.dataset.peerId='{g.TARGET_PEER}'")
        with self.assertRaises(NeedsDecision):await g.dispatch(self.page,g.SEND_JS,arg)
        self.assertEqual(await self.page.evaluate('sent'),[])
    async def test_edited_same_message_cannot_be_answered(self):
        arg=await self.prepared();await self.page.evaluate("document.querySelector('.message').textContent='Другой вопрос'")
        with self.assertRaises(NeedsDecision):await g.dispatch(self.page,g.SEND_JS,arg)
        self.assertEqual(await self.page.evaluate('sent'),[])
    async def test_no_peer_identity_is_fail_closed(self):
        await self.page.evaluate("document.querySelector('.input-message-input').removeAttribute('data-peer-id')")
        with self.assertRaises(NeedsDecision):await g.assert_target(self.page)
        self.assertEqual(await self.page.evaluate('sent'),[])
    async def test_complete_sender_never_uses_global_keyboard(self):
        import importlib.util
        from unittest.mock import Mock,AsyncMock,patch
        spec=importlib.util.spec_from_file_location('safe_sender',B/'giga-bot.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        m.WEB_DEADLINE=time.time()+120;m.CURRENT_MESSAGE=fingerprint({'mid':'1','peer_id':g.TARGET_PEER,'text':'Вопрос','buttons':['Да']})
        m.STATE_PATH=None;m.AUTONOMOUS=False
        await self.page.evaluate("""() => {
          const button=document.querySelector('.btn-send'), old=button.onclick;
          button.onclick=()=>{old();const bubble=document.createElement('div');bubble.className='bubble is-out';bubble.dataset.mid='2';const message=document.createElement('div');message.className='message';message.textContent=document.querySelector('.input-message-input').innerText;bubble.append(message);document.querySelector('.bubbles').append(bubble);document.querySelector('.input-message-input').textContent='';};
        }""")
        with patch.object(m,'ensure_telegram_contact'),patch.object(m,'run_status'),patch.object(self.page.keyboard,'press',new=AsyncMock()) as keys:
            await m.type_and_send(self.page,'Ответ',False)
            keys.assert_not_called()
        self.assertEqual(await self.page.evaluate('sent'),['Ответ'])
    async def test_switch_after_preparation_blocks_final_dispatch(self):
        arg=await self.prepared();await self.page.evaluate("document.querySelector('.input-message-input').dataset.peerId='123'")
        with self.assertRaises(NeedsDecision):await g.dispatch(self.page,g.SEND_JS,arg)
        self.assertEqual(await self.page.evaluate('sent'),[])
    async def test_manual_reply_or_edited_question_blocks(self):
        arg=await self.prepared();await self.page.evaluate("document.querySelector('.bubble').className='bubble is-out'")
        with self.assertRaises(NeedsDecision):await g.dispatch(self.page,g.SEND_JS,arg)
        self.assertEqual(await self.page.evaluate('sent'),[])
    async def test_expiry_after_sleep_blocks(self):
        arg=await self.prepared();await self.page.evaluate('window.__candidateBotScope.expires=Date.now()/1000-1')
        with self.assertRaises(NeedsDecision):await g.dispatch(self.page,g.SEND_JS,arg)
        self.assertEqual(await self.page.evaluate('sent'),[])
    async def test_user_draft_is_preserved(self):
        await self.prepared()
        with self.assertRaises(NeedsDecision):await g.require_empty_editor(self.page)
        self.assertEqual(await self.page.locator('.input-message-input').inner_text(),'Ответ')
    async def test_button_in_foreign_chat_cannot_be_clicked(self):
        await self.page.evaluate("document.querySelector('.input-message-input').dataset.peerId='123'")
        with self.assertRaises(NeedsDecision):await g.dispatch(self.page,g.BUTTON_JS,{'label':'Да','mid':'1','source_text':'Вопрос'})
        self.assertEqual(await self.page.evaluate('sent'),[])
    async def test_mousedown_only_menu_button_is_activated(self):
        await self.page.evaluate("() => {const b=document.querySelector('.reply-markup-button');b.onclick=null;b.onmousedown=()=>sent.push('menu');}")
        await g.dispatch(self.page,g.BUTTON_JS,{'label':'Да','mid':'1','source_text':'Вопрос'})
        self.assertEqual(await self.page.evaluate('sent'),['menu'])
    def test_wall_clock_and_peer_fingerprint(self):
        with self.assertRaises(NeedsDecision):g.check_deadline(100,now=101)
        a={'mid':'1','text':'same','peer_id':'1'};b={**a,'peer_id':'2'};self.assertNotEqual(fingerprint(a),fingerprint(b))
    def test_no_uncertain_reply_can_be_sent(self):
        for text in ['Информацию об оформлении нужно уточнить.','Военный билет нужно уточнить отдельно.','Готовность к командировкам необходимо уточнить.','Информации об образовании нет.']:
            self.assertIsNotNone(reply_problem(text),text)
