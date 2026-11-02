from search_options import resolve_search_fields
import argparse,re,sys,json,datetime
from common import hh_tool, HH_CONFIG, BASE
from candidate import build_system_prompt, load_profile
from vacancy_policy import vacancy_decision, application_decision
from employer_guard import ensure_full_contact, excluded_ids, ContactBlocked
from runtime import operation_lock,repeat_pass,save_json

DEFAULT_QUERIES=['системный аналитик','ведущий системный аналитик','старший системный аналитик','главный системный аналитик','системный аналитик senior','senior system analyst','lead system analyst','system analyst','fullstack аналитик','fullstack-аналитик','full-stack аналитик','аналитик ai','бизнес-аналитик ai','бизнес-аналитик']
PRESETS={'moscow':(['1'],[]),'ru-cis':(['113','5','40','9','16','28','48','97'],['REMOTE']),'abroad':(['5','40','9','16','28','1001','48','97'],['REMOTE']),'all':([],[])}

def build_command(args,profile,query=None):
    get=lambda k,d=None:getattr(args,k,d)
    base=['--config-dir',str(HH_CONFIG)]
    if args.action not in ('apply','reply'):return base+['whoami' if args.action=='whoami' else 'list-resumes']
    if not profile.get('profile_confirmed'):raise ValueError('Сначала подтвердите профиль')
    base+=['--use-ai','--openai-timeout','180']
    prompt=build_system_prompt(profile)
    if args.action=='apply':
        if not 1<=args.max<=1000 or not 1<=get('pages',1)<=100 or not 1<=get('per_page',15)<=100:raise ValueError('Лимит 1–1000, страницы и размер страницы 1–100')
        selected_query=query or args.query or next(iter(get('queries') or []),'') or (DEFAULT_QUERIES[0] if get('all_queries',False) else '')
        if not str(selected_query).strip():raise ValueError('Укажи поисковый запрос')
        cmd=['apply','--search',selected_query,'--total-pages',str(get('pages',1)),'--per-page',str(get('per_page',15)),
             '--max-responses',str(args.max),('--no-skip-tests' if get('solve_tests',False) else '--skip-tests'),'--order-by','publication_time',
             '--search-field',*resolve_search_fields(get('search_fields'),body_too=get('body_too',False)),'--force-letter','--system-prompt',prompt,
             '--message-prompt','Составь сопроводительное письмо по требованиям вакансии: приветствие и проекты, пункты соответствия требованиям на основе резюме и легенды, мотивация поиска и контакты. Вакансия: %(vacancy_name)s. Описание: %(vacancy_description)s.']
        ids=excluded_ids(profile)+(['3529'] if get('no_sber',False) else [])
        if ids:cmd+=['--excluded-employer-id',*ids]
        if get('employer_id'):cmd+=['--employer-id',*args.employer_id]
        area,formats=PRESETS[get('preset','all')]
        if area:cmd+=['--area',*area]
        if formats:cmd+=['--work-format',*formats]
    else:
        cmd=['reply-employers','--period',str(get('period',45)),'--max-pages',str(get('pages',25)),
             '--system-prompt',prompt,'--message-prompt','Ответь только на последний вопрос работодателя по подтверждённому профилю. Не придумывай условия или опыт. Коротко и прямо, обычно 1–2 предложения, без клише, вступлений и непрошеных пояснений. Контакты из профиля — если они нужны для ответа.']
    if args.resume_id:cmd+=['--resume-id',args.resume_id]
    if not args.live:cmd+=['--dry-run']
    return base+cmd

def parser():
    p=argparse.ArgumentParser(description='HH на Mac. По умолчанию предпросмотр, отправка только --live')
    p.add_argument('action',choices=['apply','reply','whoami','resumes'])
    p.add_argument('--resume-id');p.add_argument('--query',default='')
    p.add_argument('--queries',nargs='+');p.add_argument('--all-queries',action='store_true')
    p.add_argument('--max',type=int,default=10);p.add_argument('--pages',type=int,default=1);p.add_argument('--per-page',type=int,default=15)
    p.add_argument('--solve-tests',action='store_true',help='Подготовка и прохождение встроенных тестов HH')
    p.add_argument('--search-fields',nargs='+',choices=['name','description','company_name']);p.add_argument('--employer-id',nargs='+');p.add_argument('--body-too',action='store_true');p.add_argument('--no-sber',action='store_true')
    p.add_argument('--preset',choices=PRESETS,default='all');p.add_argument('--period',type=int,default=45)
    p.add_argument('--loop-minutes',type=int,default=0);p.add_argument('--every-sec',type=int,default=300)
    p.add_argument('--live',action='store_true');p.add_argument('--preview',action='store_true');p.add_argument('--plan',action='store_true',help='Проверить параметры без сети и генерации')
    return p

def run(args):
    if args.live and args.preview:raise ValueError('Выбери один режим')
    if args.loop_minutes and args.action!='reply':raise ValueError('Цикл доступен для ответов')
    if not 0<=args.loop_minutes<=1440 or not 30<=args.every_sec<=86400 or not 1<=args.period<=365:raise ValueError('Некорректный период цикла')
    if args.employer_id and any(not str(i).isdigit() for i in args.employer_id):raise ValueError('ID работодателя должен быть числом')
    profile=load_profile() if args.action in ('apply','reply') else {}
    queries=args.queries or (DEFAULT_QUERIES if args.all_queries else [args.query])
    commands=[build_command(args,profile,q) for q in queries] if args.action=='apply' else [build_command(args,profile)]
    if args.plan:
        print(json.dumps({'action':args.action,'mode':'live' if args.live else 'preview','queries':queries,'global_max':args.max,'preset':args.preset,'commands_valid':len(commands),'loop_minutes':args.loop_minutes},ensure_ascii=False));return 0
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    ledger=BASE/'.state/runs'/('hh-'+stamp+'.json')
    state={'action':args.action,'mode':'live' if args.live else 'preview','started_at':datetime.datetime.now().isoformat(),'results':[],'options':vars(args)}
    save_json(ledger,state)
    def one_pass():
        profile_now=load_profile() if args.action in ('apply','reply') else {}
        tool=hh_tool();tool.api_client.captcha_handler=None;tool.api_client.max_retries=1
        tool.controlled_error_types=(ModelUnavailable,TestSubmissionBlocked,CoverLetterNeedsReview)
        if args.action in ('apply','reply'):
            tool.employer_contact_guard=lambda v,context='':ensure_full_contact(v,tool.api_client.get,context)
        if args.action=='apply':
            print('Широкий поиск: без фильтров зарплаты, оформления, города и формата. Запреты компаний и повторы сохраняются.',flush=True)
            seen=set();counter=[0]
            from hh_search_state import VacancyRunClaims
            search_claims=VacancyRunClaims()
            tool.candidate_claim_vacancy=search_claims.claim
            from application_intents import blocks_application
            intent_path=HH_CONFIG/'application-intents.json'
            try:intents=json.loads(intent_path.read_text())
            except FileNotFoundError:intents={}
            def policy(v):
                if counter[0]>=args.max:return 'skip','Общий лимит исчерпан'
                if str(v['id']) in seen:return 'skip','Уже обработана в этом запуске'
                if str(v['id']) in intents and blocks_application(intents[str(v['id'])]):return 'skip','Ранее отправлена или прерванная отправка требует ручной проверки'
                if args.no_sber and re.search('сбер|sber',(v.get('employer') or {}).get('name',''),re.I):return 'skip','Сбер исключён для этого запуска'
                return application_decision(v,load_profile())
            def completed(v,letter,dry):
                seen.add(str(v['id']));counter[0]+=1
                if not dry:
                    intents[str(v['id'])]['status']='sent';save_json(intent_path,intents)
                state['results'].append({'vacancy_id':str(v['id']),'employer':(v.get('employer') or {}).get('name'),'status':'preview' if dry else 'sent','letter':letter})
                save_json(ledger,state)
            def intent(v,params):
                vid=str(v['id'])
                previous=intents.get(vid)
                if vid in intents and blocks_application(previous):raise RuntimeError('Повтор отправки остановлен')
                intents[vid]={'status':'attempting','resume_id':params['resume_id'],'run':stamp,'letter':params['message'],'test_answers':params.get('test_answers')}
                if previous is not None:
                    intents[vid]['previous_reconciliation']=previous.get('reconciliation')
                save_json(intent_path,intents)
            def test_report(v, status, questions=None, reason=None):
                state.setdefault('tests',[]).append({'vacancy_id':str(v['id']),'status':status,
                    'questions':questions or [],'reason':reason})
                save_json(ledger,state)
            from cover_letters import generate as generate_cover_letter
            tool.candidate_cover_letter=lambda vacancy:generate_cover_letter(tool,load_profile(),vacancy)
            tool.vacancy_test_report=test_report
            tool.application_intent=intent
            tool.candidate_vacancy_policy=policy
            tool.application_result=completed
            tool.application_budget_exhausted=lambda:counter[0]>=args.max
            for q in queries:
                if counter[0]>=args.max:break
                code=tool.run(build_command(args,profile_now,q))
                if code not in (None,0):return code
            return 0
        if args.action=='reply':
            def reply_result(nid,mid,letter,dry):
                state['results'].append({'negotiation_id':str(nid),'message_id':str(mid),'status':'preview' if dry else 'sent','letter':letter})
                save_json(ledger,state)
            tool.reply_result=reply_result
        return tool.run(build_command(args,profile_now))
    from cover_letters import CoverLetterNeedsReview
    from model_availability import ModelUnavailable
    from hh_test_transport import TestSubmissionBlocked
    from hh_captcha import CaptchaWaitExpired
    try:
        with operation_lock('hh'):
            code=repeat_pass(one_pass,args.loop_minutes,args.every_sec)
    except (CaptchaWaitExpired,ModelUnavailable,TestSubmissionBlocked,CoverLetterNeedsReview) as e:
        print(str(e),flush=True);state['message']=str(e);code=20
    except KeyboardInterrupt:
        state['message']='Запуск остановлен';code=130
    state.update(status='completed' if code==0 else 'needs_attention' if code==20 else 'stopped' if code==130 else 'failed',finished_at=datetime.datetime.now().isoformat());save_json(ledger,state)
    return code

def main():
    try:return run(parser().parse_args())
    except (ValueError,RuntimeError,ContactBlocked) as e:print(str(e),file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
