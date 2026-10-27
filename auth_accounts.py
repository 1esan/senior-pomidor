import asyncio, json, secrets, sys, time, logging
from urllib.parse import urlsplit, parse_qs, urljoin
from common import BASE, hh_tool, write_status
from playwright.async_api import async_playwright

logging.getLogger('hh-applicant-tool').setLevel(logging.WARNING)

async def existing_oauth_code(tool, context, url, flow_state):
    # Reuse the user's own browser session. No OTP is read or submitted here.
    for cookie in await context.cookies():
        if 'hh.' in cookie.get('domain',''):
            tool.session.cookies.set(cookie['name'],cookie['value'],domain=cookie['domain'],path=cookie.get('path','/'))
    for _ in range(10):
        if url.startswith('hhandroid://oauthresponse'):
            params=parse_qs(urlsplit(url).query)
            if params.get('state') and params['state'][0]!=flow_state:raise RuntimeError('oauth_state_mismatch')
            return params.get('code',[None])[0]
        target=urlsplit(url)
        if target.scheme!='https' or not (target.hostname=='hh.ru' or (target.hostname or '').endswith('.hh.ru')):return None
        response=await asyncio.to_thread(tool.session.get,url,allow_redirects=False,timeout=30)
        if response.status_code not in (301,302,303,307,308):return None
        location=response.headers.get('location')
        if not location:return None
        url=urljoin(url,location)
    return None

async def main(channel):
    write_status(channel, {'status':'opening_browser'})
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(BASE/'.state'/f'{channel}_browser'), headless=False,
            viewport={'width':1180,'height':840})
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            if channel == 'telegram':
                await page.goto('https://web.telegram.org/k/', wait_until='domcontentloaded',timeout=60000)
                write_status(channel, {'status':'waiting_for_login','message':'Войди в Telegram через QR или номер телефона в окне Chromium.'})
                started=time.monotonic()
                while time.monotonic()-started < 900:
                    if await page.locator('#column-left .chatlist, .chatlist-container .chatlist, #column-left .input-search').count():
                        write_status(channel, {'status':'connected','method':'telegram_web','verified_at':time.strftime('%Y-%m-%dT%H:%M:%S'),'session_saved':True})
                        print('TELEGRAM_LOGIN_VERIFIED');return
                    await asyncio.sleep(2)
                raise RuntimeError('login_timeout')
            tool=hh_tool()
            tool.api_client.captcha_handler=None
            flow_state=secrets.token_urlsafe(24)
            oauth=tool.api_client.oauth_client
            oauth.state=flow_state
            callback=asyncio.get_running_loop().create_future()
            def receive(url):
                parsed=urlsplit(url)
                if parsed.scheme!='hhandroid' or parsed.netloc!='oauthresponse':return
                params=parse_qs(parsed.query)
                if params.get('state') and params['state'][0]!=flow_state:
                    if not callback.done():callback.set_exception(RuntimeError('oauth_state_mismatch'))
                    return
                code=params.get('code',[None])[0]
                if code and not callback.done():callback.set_result(code)
            async def inspect_response(response):
                if response.status in (301,302,303,307,308):
                    headers=await response.all_headers()
                    receive(headers.get('location',''))
            async def route_request(route):
                if route.request.url.startswith('hhandroid://'):
                    receive(route.request.url);await route.abort()
                else:await route.continue_()
            page.on('response', inspect_response)
            page.on('request',lambda request:receive(request.url))
            await context.route('**/*',route_request)
            url=oauth.authorize_url(role='applicant',force_role='true',skip_choose_account='true')
            write_status(channel,{'status':'verifying_api','message':'Проверяю уже выполненный вход и завершение OAuth.'})
            code=await existing_oauth_code(tool,context,url,flow_state)
            if not code:
                try:await page.goto(url,wait_until='domcontentloaded',timeout=60000)
                except Exception:
                    if not callback.done():raise
                write_status(channel,{'status':'waiting_for_login','message':'Войди в свой hh.ru в окне Chromium; пароль и код вводи только на странице hh.ru.'})
                code=await asyncio.wait_for(callback,timeout=900)
            write_status(channel,{'status':'verifying_api'})
            token=await asyncio.to_thread(oauth.authenticate,code)
            tool.api_client.handle_access_token(token)
            tool.save_token()
            tool.auth_config._path.chmod(0o600)
            me=await asyncio.to_thread(tool.get_me)
            resumes=await asyncio.to_thread(tool.get_resumes)
            for cookie in await context.cookies():
                if 'hh.' in cookie.get('domain',''):
                    tool.session.cookies.set(cookie['name'],cookie['value'],domain=cookie['domain'],path=cookie.get('path','/'))
            tool.save_cookies()
            if tool.cookies_file.exists():tool.cookies_file.chmod(0o600)
            tool.save_token()
            write_status(channel,{'status':'connected','method':'hh_oauth','api_me_verified':bool(me.get('id')),'resume_count':len(resumes),'verified_at':time.strftime('%Y-%m-%dT%H:%M:%S'),'session_saved':True})
            (BASE/'.state/hh/resumes.json').write_text(json.dumps([{'id':r.get('id'),'title':r.get('title'),'status':(r.get('status') or {}).get('id')} for r in resumes],ensure_ascii=False,indent=2))
            (BASE/'.state/hh/resumes.json').chmod(0o600)
            print('HH_LOGIN_AND_API_VERIFIED')
        except Exception as error:
            code=type(error).__name__
            message='Вход не завершён. Повтори его в окне браузера.'
            if 'login_timeout' in str(error):message='Истекло время ожидания входа.'
            write_status(channel,{'status':'failed','error':code,'message':message})
            print(channel.upper()+'_LOGIN_FAILED',code)
        finally:
            await context.close()

if __name__=='__main__':
    channel=sys.argv[1] if len(sys.argv)>1 else ''
    if channel not in ('hh','telegram'):raise SystemExit('Use hh or telegram')
    asyncio.run(main(channel))
