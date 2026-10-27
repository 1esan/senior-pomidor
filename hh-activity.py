"""
Активность автоответчика по ЛОГАМ (без единого запроса к hh.ru).
Читает лог hh-applicant-tool и giga-bot, считает по дням, пишет hh-activity.html.

  py hh-activity.py
"""

from common import BASE, HH_CONFIG
import re, json, html
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta, timezone

RECENT = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")  # ошибки только за последние ~6 дней

HH_LOGS = [
    HH_CONFIG / 'log.txt.1',
    HH_CONFIG / 'log.txt',
]
GIGA_LOG = BASE / "logs" / "giga-bot.log"
OUT = BASE / "hh-activity.html"

TS = re.compile(r"^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2}")
day = lambda s: (m.group(1) if (m := TS.match(s)) else None)

days = defaultdict(lambda: {"apply": 0, "letter": 0, "chat": 0, "reject_seen": 0, "err": 0, "giga": 0, "giga_preview": 0})
last_line = {"hh": "", "giga": ""}
errors = []

for lp in HH_LOGS:
    if not lp.exists():
        continue
    for raw in lp.read_text(encoding="utf-8", errors="replace").splitlines():
        line = re.sub(r"\x1b\[[0-9;]*m", "", raw)
        d = day(line)
        if not d:
            continue
        last_line["hh"] = re.sub(r"(?i)(bearer\s+|(?:access_token|refresh_token|authorization)[\s\"\':=]+)[^\s,}]+", r"\1[скрыто]", line)[:200]
        if "201 POST https://api.hh.ru/negotiations with params" in line:
            days[d]["apply"] += 1
            if "'message': ''" not in line:
                days[d]["letter"] += 1
        elif re.search(r"20[14] POST https://api\.hh\.ru/negotiations/\d+/messages", line):
            days[d]["chat"] += 1
        elif "Вы получили отказ" in line or "Пришел отказ" in line:
            days[d]["reject_seen"] += 1
        elif re.search(r"\b(prohibited|negotiations-limit|Traceback|\[E\]|ERROR)\b", line) and "disabled_by_employer" not in line:
            days[d]["err"] += 1
            if d >= RECENT and len(errors) < 25:
                errors.append(line[:200])

if GIGA_LOG.exists():
    for raw in GIGA_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        line = re.sub(r"\x1b\[[0-9;]*m", "", raw)
        d = day(line)
        if not d:
            continue
        last_line["giga"] = line[:200]
        if "TELEGRAM_CONFIRMED:" in line:
            days[d]["giga"] += 1
        elif "TELEGRAM_PREVIEW:" in line:
            days[d]["giga_preview"] += 1

batch_ids = set()
application_ids = set()
ledger_days = defaultdict(lambda: {"apply":0,"chat":0,"letter":0})
verified_batches = 0
batch_letters = 0
for ledger in (BASE / ".state" / "batches").glob("*/dispatch.json"):
    data = json.loads(ledger.read_text())
    for result in data.get("results", []):
        identity = str(result.get("negotiation_id") or result.get("id"))
        if result.get("status") not in ("accepted", "verified") or identity in batch_ids:
            continue
        batch_ids.add(identity)
        if result.get('vacancy_id'): application_ids.add(str(result['vacancy_id']))
        verified_batches += 1
        date_match=re.search(r'(20\d{6})',ledger.parent.name)
        batch_day=result.get('created_at') or result.get('at')
        if batch_day: batch_day=str(batch_day)[:10]
        elif date_match:
            raw_date=date_match.group(1);batch_day=raw_date[:4]+'-'+raw_date[4:6]+'-'+raw_date[6:8]
        if batch_day:
            ledger_days[batch_day]['apply']+=1
            ledger_days[batch_day]['letter']+=bool(result.get('letter'))
        batch_letters += bool(result.get("letter"))

recorded_apps=verified_batches
recorded_replies=0
recorded_previews=0
seen_runs=set()
for ledger in (BASE/'.state/runs').glob('hh-*.json'):
    data=json.loads(ledger.read_text())
    for r in data.get('results',[]):
        ident=(data.get('action'),r.get('vacancy_id'),r.get('negotiation_id'),r.get('message_id'),r.get('status'))
        if ident in seen_runs:continue
        seen_runs.add(ident)
        if r.get('status')=='preview':recorded_previews+=1
        elif r.get('status')=='sent':
            if data.get('action')=='apply' and str(r.get('vacancy_id')) not in application_ids:
                application_ids.add(str(r.get('vacancy_id')));recorded_apps+=1
                if data.get('started_at'):
                    ledger_days[data['started_at'][:10]]['apply']+=1
                    ledger_days[data['started_at'][:10]]['letter']+=bool(r.get('letter'))
            elif data.get('action')=='reply':
                recorded_replies+=1
                if data.get('started_at'):ledger_days[data['started_at'][:10]]['chat']+=1
try:helper_records=json.loads((BASE/'.state/outgoing-helper.json').read_text())
except FileNotFoundError:helper_records={}
recorded_replies+=sum(r.get('status')=='sent' for r in helper_records.values())

http_tot = {k:sum(v[k] for v in days.values()) for k in ('apply','letter','chat')}
for d,counts in ledger_days.items():
    for k in ('apply','letter','chat'): days[d][k]=max(days[d][k],counts[k])
series = [{"date": k, **v} for k, v in sorted(days.items())]
tot = {k: sum(x[k] for x in series) for k in ("apply", "letter", "chat", "reject_seen", "err", "giga", "giga_preview")}
gen = datetime.now(timezone.utc).isoformat()

from statistics_store import publish, recent_application_runs
from conversation_statistics import collect
conversations = collect(BASE)
activity_data = {"conversations": conversations,"series": series, "tot": tot, "http_tot":http_tot, "last": last_line, "errors": errors, "gen": gen, "verified_batches": verified_batches, "batch_letters": batch_letters,"recorded_apps":recorded_apps,"recorded_replies":recorded_replies,"recorded_previews":recorded_previews}
publish(BASE,"activity",activity_data)
latest_run=None
for file in sorted((BASE/".state/runs").glob("hh-*.json"),key=lambda f:f.stat().st_mtime,reverse=True):
    run=json.loads(file.read_text())
    if run.get("action")=="apply" and run.get("mode")=="live":
        latest_run={"sent":sum(r.get("status")=="sent" for r in run.get("results",[])),"started_at":run.get("started_at"),"finished_at":run.get("finished_at"),"status":run.get("status","running")}
        break
if latest_run is not None:latest_run["recent_application_runs"]=recent_application_runs(BASE)
publish(BASE,"latest_run",latest_run)
DATA = "{}"

temporary = OUT.with_suffix(".html.tmp")
temporary.write_text("""<meta charset="utf-8"><title>Интервью · Сеньор Помидор</title>
<style>
:root{--pl:#f4f1ef;--sf:#fff;--ink:#1b1613;--ink2:#6b615b;--mut:#978c85;--ln:#ece5e1;--hh:#e0301e;--bl:#256abf;--gn:#0ca30c;--rd:#d03b3b;--bar:#efeae6;color-scheme:light}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--pl:#100f0e;--sf:#1a1817;--ink:#f3efeb;--ink2:#bcb3aa;--mut:#8b8179;--ln:#2c2926;--hh:#f0503f;--bl:#5c9ae8;--gn:#25b525;--rd:#e05a5a;--bar:#2a2724}}
:root[data-theme=dark]{--pl:#100f0e;--sf:#1a1817;--ink:#f3efeb;--ink2:#bcb3aa;--mut:#8b8179;--ln:#2c2926;--hh:#f0503f;--bl:#5c9ae8;--gn:#25b525;--rd:#e05a5a;--bar:#2a2724}
*{box-sizing:border-box}body{margin:0;background:var(--pl);color:var(--ink);font-family:"Golos Text",system-ui,sans-serif;font-size:15px}
.wrap{max-width:960px;margin:0 auto;padding:32px 24px 64px}
h1{font-size:30px;margin:6px 0 0;letter-spacing:-.02em}
.br{font-size:12px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--ink2);display:flex;align-items:center;gap:9px}
.br .d{width:9px;height:9px;border-radius:2px;background:var(--hh)}
p.sub{color:var(--ink2);font-size:13.5px;margin:6px 0 26px}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:26px}
.t{background:var(--sf);border:1px solid var(--ln);border-radius:12px;padding:15px 16px}
.t .n{font-size:27px;font-weight:700;letter-spacing:-.02em}
.t .l{font-size:12.5px;color:var(--ink2);margin-top:3px}
.card{background:var(--sf);border:1px solid var(--ln);border-radius:14px;padding:20px 22px;margin-bottom:20px}
.card h2{font-size:14px;text-transform:uppercase;letter-spacing:.08em;margin:0 0 16px}
svg{display:block;width:100%;height:auto}
.legend{display:flex;gap:16px;font-size:12.5px;color:var(--ink2);margin-bottom:8px}
.legend i{width:20px;height:3px;border-radius:2px;display:inline-block;vertical-align:middle;margin-right:6px}
.mono{font-family:"JetBrains Mono",monospace;font-size:12px}
.last{color:var(--ink2);font-size:12.5px;word-break:break-all}
.table-scroll{overflow:auto;max-height:620px}table{border-collapse:collapse;width:100%;min-width:650px}th,td{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid var(--ln);font-size:13px}th{position:sticky;top:0;background:var(--sf)}td:first-child{min-width:240px}td div{font-size:12px;color:var(--ink2);margin-top:4px}td p{white-space:pre-wrap;overflow-wrap:anywhere;max-width:520px}button{padding:10px 14px;cursor:pointer}a{color:var(--bl)}.err{background:color-mix(in srgb,var(--rd) 10%,transparent);border:1px solid color-mix(in srgb,var(--rd) 30%,transparent);border-radius:10px;padding:12px 14px;font-size:12px;color:var(--rd);max-height:180px;overflow:auto}
footer{margin-top:32px;border-top:1px solid var(--ln);padding-top:14px;font-size:12px;color:var(--mut)}
@media(max-width:640px){.tiles{grid-template-columns:repeat(2,1fr)}}
</style>
<div class="wrap">
<div class="br"><span class="d"></span> Сеньор Помидор · результаты</div>
<h1>Интервью ГигаРекрутёра</h1><p class="sub">Завершённые интервью, обратная связь и результаты откликов — по каждой вакансии.</p>
<div class="tiles eg-result-metrics" id="result-metrics" aria-label="Результаты интервью"></div>
<div class="eg-interview-state"><p id="telegram-note" class="last"></p><button type="button" class="secondary" data-application-filter="attention" id="attention-shortcut" hidden>Требуют внимания</button><a class="link secondary" href="http://127.0.0.1:8768/#launch/log">Журнал запуска ↗</a></div>
<p id="conversation-freshness" class="last" aria-live="polite"></p><p id="application-freshness" class="last"></p>
<section class="card eg-completion-chart"><div class="eg-interview-heading"><h2>Пройденные интервью по дням</h2><div class="eg-outcome-filters" aria-label="Период графика"><button type="button" class="secondary" data-chart-days="7" aria-pressed="true">7 дней</button><button type="button" class="secondary" data-chart-days="30" aria-pressed="false">30 дней</button></div></div><div id="interview-completion-chart" class="eg-completion-bars"></div></section>
<section class="card" id="conversations">
<h2>Вакансии и результаты</h2>
<div class="eg-outcome-filters" role="group" aria-label="Результат отклика"><button type="button" class="secondary" data-application-filter="all">Все</button><button type="button" class="secondary" data-application-filter="waiting_interview">Ожидают интервью</button><button type="button" class="secondary" data-application-filter="in_progress">Интервью начато</button><button type="button" class="secondary" data-application-filter="completed">Интервью пройдено</button><button type="button" class="secondary" data-application-filter="rejected">Все отказы</button><button type="button" class="secondary" data-application-filter="done_rejected">Интервью пройдено + отказ</button><button type="button" class="secondary" data-application-filter="rejected_unfinished">Отказ без завершённого интервью</button><button type="button" class="secondary" data-application-filter="pending_decision">Пройдено · ждём обратной связи</button></div><label>Найти вакансию <input id="interview-search" type="search" placeholder="Название или ID вакансии" style="font:inherit;padding:9px;width:min(100%,420px)"></label>
<p id="interview-count" class="last"></p><div class="table-scroll" id="interview-table-scroll"><table><thead><tr><th>Вакансия</th><th>Интервью</th><th>Результат отклика</th><th>Последняя активность</th></tr></thead><tbody id="interviews"></tbody></table></div>
<p class="last">Завершение интервью сохраняется независимо от результата HH. «Пройдено + отказ» означает два подтверждённых факта; порядок событий указан в деталях.</p>
</section>
<details class="card eg-secondary-report" id="hh-extra"><summary>Переписка на hh.ru</summary>

<p id="hh-conversation-note" class="last"></p>
<div class="table-scroll"><table><thead><tr><th>Компания / вакансия</th><th>Кто отвечает</th><th>Сообщения</th><th>Последнее сообщение</th></tr></thead><tbody id="hh-conversations"></tbody></table></div>
<button id="hh-more" type="button">Показать все переписки hh.ru</button>
<p class="last">Данные hh.ru — последний полный снимок переписки. Для обновления: в панели → «Отчёты» → «Обновить выгрузку и аналитику». Локальное обновление активности не обращается к hh.ru.</p>
</details>

<details class="card eg-secondary-report" id="technical-details"><summary>Диагностика и журналы</summary>
<div class="tiles" id="conversation-tiles" hidden></div><div class="tiles" id="application-tiles" hidden></div><div id="conversation-errors" hidden></div>
<p class="sub" id="sub"></p>
<div class="tiles" id="tiles"></div>
<div class="card">
  <h2>По дням</h2>
  <div class="legend"><span><i style="background:var(--bl)"></i>отклики</span><span><i style="background:var(--gn)"></i>ответы в чат</span><span><i style="background:var(--rd)"></i>ошибки</span></div>
  <div id="chart"></div>
</div>
<div class="card">
  <h2>Последняя строка лога</h2>
  <div class="last mono" id="lasthh"></div>
  <div class="last mono" id="lastgiga" style="margin-top:6px"></div>
</div>
<div class="card" id="errcard" hidden>
  <h2>Ошибки за последние дни</h2>
  <div class="err mono" id="errs"></div>
</div>
</details><footer>Интервью обновляются из локальной истории бота. Статусы HH — из отдельного снимка. Даты обновления показаны выше.</footer>
</div>
<script id="d" type="application/json">""" + DATA + """</script>
<script>
if(location.protocol==='file:'&&!window.__REPORT_EXPORT__)location.replace('http://127.0.0.1:8768/reports/activity');
let D=JSON.parse(document.getElementById('d').textContent);
const nf=n=>n.toLocaleString('ru-RU');

let C=D.conversations;
const fmtTime=value=>value?new Date(typeof value==='number'?value*1000:value).toLocaleString('ru-RU'):'—';
function textNode(tag,text){const e=document.createElement(tag);e.textContent=text??'—';return e;}
const stateLabels={legacy_review:'Проверить старую привязку',queued:'В очереди',completed:'Завершено',paused:'Приостановлено',error:'Требует внимания',waiting_recruiter:'Ждём рекрутёра',reply_delay:'Пауза перед ответом',generating:'Готовит ответ',model_retry:'Повтор генерации',running:'В работе'};
let applicationFilter='all';try{applicationFilter=sessionStorage.getItem('interview-outcome-filter')||'all';}catch{}
const needsAttention=r=>['error','paused','legacy_review'].includes(r.status);
const dayKey=value=>new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(typeof value==='number'?value*1000:value));
const completed=r=>r.interview_stage==='completed'||r.status==='completed';
const applicationFilters={all:()=>true,today_completed:r=>completed(r)&&r.completed_at&&dayKey(r.completed_at)===dayKey(new Date()),attention:needsAttention,waiting_interview:r=>r.journey_code==='waiting_interview',in_progress:r=>r.journey_code==='interview_in_progress',completed:r=>r.interview_stage==='completed',rejected:r=>r.application_outcome==='rejected',done_rejected:r=>r.application_outcome==='rejected'&&r.interview_stage==='completed',rejected_unfinished:r=>r.application_outcome==='rejected'&&r.interview_stage!=='completed',pending_decision:r=>r.journey_code==='completed_waiting'};
function renderInterviews(){
 const body=document.getElementById('interviews'),scroller=document.getElementById('interview-table-scroll'),top=scroller.scrollTop;
 const openIds=new Set([...body.querySelectorAll('details[open]')].map(e=>e.dataset.vacancyId));body.replaceChildren();
 const query=document.getElementById('interview-search').value.toLocaleLowerCase('ru-RU');
 const predicate=applicationFilters[applicationFilter]||applicationFilters.all;
 document.querySelectorAll('[data-application-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.applicationFilter===applicationFilter)));
 document.querySelectorAll('[data-card-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.cardFilter===applicationFilter)));
 const rows=(C?.telegram.rows||[]).filter(r=>predicate(r)&&(r.name+' '+r.company+' '+r.vacancy_id).toLocaleLowerCase('ru-RU').includes(query));
 for(const r of rows){
  const tr=document.createElement('tr'),name=document.createElement('td');
  const link=textNode('a',r.name);link.href='https://hh.ru/vacancy/'+encodeURIComponent(r.vacancy_id);link.target='_blank';link.rel='noreferrer';name.append(link,textNode('div',r.company+' · '+r.vacancy_id));
  const detail=document.createElement('details');detail.dataset.vacancyId=r.vacancy_id;detail.open=openIds.has(r.vacancy_id);detail.append(textNode('summary','Детали'));
  detail.append(textNode('p','Исходный статус HH: '+(r.application_label||'неизвестен')+(r.application_state?' ('+r.application_state+')':'')));
  if(r.application_id)detail.append(textNode('p','ID отклика: '+r.application_id+' · снимок HH: '+fmtTime(r.application_snapshot_at)));
  if(r.completed_at)detail.append(textNode('p','Интервью завершено: '+fmtTime(r.completed_at)));
  if(r.application_outcome==='rejected'&&r.interview_stage==='completed')detail.append(textNode('p',r.rejection_sequence==='after_interview'?'Отказ зафиксирован после интервью':r.rejection_sequence==='before_completion'?'Отказ зафиксирован до завершения интервью':'Порядок завершения интервью и получения отказа не установлен'));
  detail.append(textNode('p',r.journey_label||'Отклик отправлен'));
  if(r.runtime_message)detail.append(textNode('p',r.runtime_message));if(r.last_question)detail.append(textNode('p','Вопрос: '+r.last_question));if(r.last_answer)detail.append(textNode('p','Ответ: '+r.last_answer));name.append(detail);
  const status=textNode('td','');
  const stage=completed(r)?'Пройдено':needsAttention(r)?(r.status==='legacy_review'?'Нужна сверка':'Приостановлено'):r.interview_stage==='in_progress'?(stateLabels[r.status]||'В процессе'):'Не начато';
  const stageBadge=textNode('span',stage);stageBadge.className='eg-outcome';stageBadge.dataset.journey=completed(r)?'completed_waiting':r.interview_stage==='in_progress'?'interview_in_progress':'unknown';status.append(stageBadge);
  const outcome=textNode('td',''),label=r.application_outcome==='rejected'?'Отказ':completed(r)?'Ожидает обратной связи':r.application_label||'Отклик отправлен';
  const resultBadge=textNode('span',label);resultBadge.className='eg-outcome';resultBadge.dataset.outcome=r.application_outcome||'unknown';outcome.append(resultBadge);
  tr.append(name,status,outcome,textNode('td',fmtTime(r.last_at||r.application_updated_at)));body.append(tr);
 }
 document.getElementById('interview-count').textContent='Показано: '+rows.length+' из '+(C?.telegram.rows||[]).length;scroller.scrollTop=top;
 if(!rows.length){const td=textNode('td','Нет откликов по выбранному фильтру');td.colSpan=4;const tr=document.createElement('tr');tr.append(td);body.append(tr);}
}
let allHH=false;
function renderHH(){
 const body=document.getElementById('hh-conversations');body.replaceChildren();
 const rows=[...(C?.hh.rows||[])].sort((a,b)=>Number(b.waiting_us)-Number(a.waiting_us)||String(b.last_at||'').localeCompare(String(a.last_at||'')));
 for(const r of rows.slice(0,allHH?rows.length:20)){
  const tr=document.createElement('tr');const name=textNode('td',r.company+' · '+r.name);name.append(textNode('div',r.status));
  const last=textNode('td',r.last_text);last.append(textNode('div',fmtTime(r.last_at)));
  tr.append(name,textNode('td',r.waiting_us?'Работодатель написал последним · проверить':'Нет открытого вопроса по снимку'),textNode('td',r.messages_in+' входящих / '+r.messages_out+' исходящих'),last);body.append(tr);
 }
 document.getElementById('hh-more').hidden=allHH||rows.length<=20;
 if(!rows.length){const tr=document.createElement('tr'),td=textNode('td','В локальной выгрузке нет переписок');td.colSpan=4;tr.append(td);body.append(tr);}
}
let chartDays=7;
function setInterviewFilter(value){applicationFilter=value;try{sessionStorage.setItem('interview-outcome-filter',value);}catch{}renderInterviews();}
function renderCompletionChart(){
 const chart=document.getElementById('interview-completion-chart');chart.replaceChildren();
 const counts=new Map();for(const row of C?.telegram.rows||[])if(completed(row)&&row.completed_at){const day=dayKey(row.completed_at);counts.set(day,(counts.get(day)||0)+1);}
 const today=dayKey(new Date()),days=[];for(let n=chartDays-1;n>=0;n--){const date=new Date(today+'T12:00:00+03:00');date.setUTCDate(date.getUTCDate()-n);const key=dayKey(date);days.push({key,count:counts.get(key)||0});}
 const max=Math.max(1,...days.map(d=>d.count));chart.style.setProperty('--day-count',String(chartDays));
 for(const d of days){const item=document.createElement('div');item.className='eg-completion-day';item.title=d.key+': '+d.count+' интервью';const number=textNode('span',d.count),track=document.createElement('div'),bar=document.createElement('i'),date=textNode('small',d.key.slice(8)+'.'+d.key.slice(5,7));track.className='eg-completion-track';bar.style.height=d.count?(d.count/max*100)+'%':'2px';bar.className=d.count?'':'empty';track.append(bar);item.append(number,track,date);chart.append(item);}
 document.querySelectorAll('[data-chart-days]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.chartDays)===chartDays)));
}
function renderConversations(){
 if(!C){document.getElementById('conversation-freshness').textContent='Статистика интервью ещё не собрана';return;}
 const t=C.telegram,rows=t.rows||[],k=C.applications?.counts||{},done=rows.filter(completed),today=done.filter(r=>r.completed_at&&dayKey(r.completed_at)===dayKey(new Date())).length;
 const cards=[[today,'Пройдено сегодня','today_completed'],[done.length,'Пройдено всего','completed'],[k.awaiting_outcome??rows.filter(r=>r.journey_code==='completed_waiting').length,'Ожидают обратной связи','pending_decision'],[k.completed_and_rejected??rows.filter(r=>completed(r)&&r.application_outcome==='rejected').length,'Пройдено + отказ','done_rejected']];
 const metrics=document.getElementById('result-metrics');metrics.replaceChildren();for(const [n,label,filter] of cards){const button=document.createElement('button');button.type='button';button.className='t eg-interview-metric';button.dataset.cardFilter=filter;button.setAttribute('aria-label',label+': '+n);button.append(textNode('strong',n),textNode('span',label));button.onclick=()=>setInterviewFilter(filter);metrics.append(button);}
 const attention=rows.filter(needsAttention),active=rows.find(r=>['running','reply_delay','waiting_recruiter','generating','model_retry'].includes(r.status));
 document.getElementById('telegram-note').textContent=t.live?('Интервью выполняется'+(active?' · '+active.name+' · '+(stateLabels[active.status]||'В работе'):'')):'Интервью сейчас не выполняются';
 const shortcut=document.getElementById('attention-shortcut');shortcut.hidden=!attention.length;shortcut.textContent='Требуют внимания: '+attention.length;
 document.getElementById('conversation-freshness').textContent='Интервью: '+fmtTime(C.generated_at)+' · обновление без перезагрузки страницы';
 const app=C.applications;document.getElementById('application-freshness').textContent='Статусы HH: '+fmtTime(app?.generated_at)+(app?.monitor?.status==='deferred'?' · следующая проверка отложена: канал HH занят или недоступен':'');
 document.getElementById('hh-conversation-note').textContent='Полный снимок переписки HH: '+fmtTime(C.hh.generated_at);
 renderInterviews();renderHH();renderCompletionChart();
}
document.querySelectorAll('[data-application-filter]').forEach(b=>b.addEventListener('click',()=>setInterviewFilter(b.dataset.applicationFilter)));
document.querySelectorAll('[data-chart-days]').forEach(b=>b.addEventListener('click',()=>{chartDays=Number(b.dataset.chartDays);renderCompletionChart();}));
document.getElementById('interview-search').addEventListener('input',renderInterviews);document.getElementById('hh-more').onclick=()=>{allHH=true;renderHH();};
renderConversations();
let refreshPending=false;
if(location.protocol==='http:')setInterval(async()=>{if(refreshPending||document.hidden)return;refreshPending=true;try{const response=await fetch('/reports/meta');if(!response.ok)return;const meta=await response.json();if(meta.activity?.source?.generated_at===D.gen)return;const updated=await fetch('/reports/statistics');if(!updated.ok)return;const data=await updated.json();if(!data.activity)return;D=data.activity;C=D.conversations;renderConversations();renderLegacyDiagnostics();}catch{document.getElementById('conversation-freshness').textContent='Не удалось проверить обновления; показан последний снимок: '+fmtTime(C?.generated_at);}finally{refreshPending=false;}},5000);
function renderLegacyDiagnostics(){
 document.getElementById('tiles').replaceChildren();

const ago=(Date.now()-new Date(D.gen))/60000;
document.getElementById('sub').textContent='обновлено '+(ago<2?'только что':ago<90?Math.round(ago)+' мин назад':Math.round(ago/60)+' ч назад')+' · по логам; отдельно подтверждено откликов: '+D.verified_batches+' (откликов подтверждено в партиях) · предпросмотры не считаются отправками';
[[D.recorded_apps,'откликов по журналам отправки'],[D.recorded_replies,'сообщений по журналам отправки'],[D.recorded_previews,'предпросмотров по журналам'],[D.http_tot.apply,'откликов в HTTP-журнале'],[D.http_tot.letter,'писем в HTTP-журнале'],[D.http_tot.chat,'сообщений в HTTP-журнале'],[D.tot.giga,'подтверждений отправки в Telegram по журналу']].forEach(([n,l])=>{
  document.getElementById('tiles').insertAdjacentHTML('beforeend',`<div class="t"><div class="n">${nf(n)}</div><div class="l">${l}</div></div>`);
});
document.getElementById('lasthh').textContent='hh: '+(D.last.hh||'—');
document.getElementById('lastgiga').textContent='giga: '+(D.last.giga||'—');
if(D.errors.length){document.getElementById('errcard').hidden=false;document.getElementById('errs').innerHTML=D.errors.map(e=>e.replace(/</g,'&lt;')).join('<br>');}
(function(){
  const s=D.series;if(!s.length){document.getElementById('chart').textContent='нет данных в логах';return;}
  const W=900,H=250,ml=32,mr=12,mt=16,mb=32,iw=W-ml-mr,ih=H-mt-mb;
  const mx=Math.max(1,...s.flatMap(d=>[d.apply,d.chat,d.err]));
  const yTop=Math.ceil(mx/20)*20||20;
  const x=i=>ml+(s.length<2?iw/2:i/(s.length-1)*iw);
  const y=v=>mt+ih-v/yTop*ih;
  const bw=Math.min(22,iw/s.length*0.6);
  let g='<svg viewBox="0 0 '+W+' '+H+'">';
  [0,yTop/2,yTop].forEach(t=>{g+=`<line x1="${ml}" x2="${W-mr}" y1="${y(t)}" y2="${y(t)}" stroke="var(--ln)"/><text x="${ml-7}" y="${y(t)+4}" text-anchor="end" font-size="10" fill="var(--mut)" font-family="JetBrains Mono,monospace">${t}</text>`;});
  s.forEach((d,i)=>{if(d.apply){const by=y(d.apply);g+=`<rect x="${(x(i)-bw/2).toFixed(1)}" y="${by.toFixed(1)}" width="${bw.toFixed(1)}" height="${(mt+ih-by).toFixed(1)}" rx="3" fill="var(--bl)"/>`;if(d.apply>=yTop*0.35)g+=`<text x="${x(i).toFixed(1)}" y="${(by-5).toFixed(1)}" text-anchor="middle" font-size="10" font-weight="600" fill="var(--bl)" font-family="JetBrains Mono,monospace">${d.apply}</text>`;}});
  const ln=(k,c)=>{const p=s.map((d,i)=>x(i).toFixed(1)+','+y(d[k]).toFixed(1)).join(' ');let o=`<polyline points="${p}" fill="none" stroke="${c}" stroke-width="2.2"/>`;s.forEach((d,i)=>{if(d[k]>0)o+=`<circle cx="${x(i).toFixed(1)}" cy="${y(d[k]).toFixed(1)}" r="2.8" fill="${c}"/>`;});return o;};
  g+=ln('chat','var(--gn)')+ln('err','var(--rd)');
  s.forEach((d,i)=>{if(i%2&&i!==s.length-1)return;g+=`<text x="${x(i).toFixed(1)}" y="${H-10}" text-anchor="middle" font-size="10" fill="var(--mut)" font-family="JetBrains Mono,monospace">${d.date.slice(8)}.${d.date.slice(5,7)}</text>`;});
  g+=`<line x1="${ml}" x2="${W-mr}" y1="${mt+ih}" y2="${mt+ih}" stroke="var(--ink2)"/></svg>`;
  document.getElementById('chart').innerHTML=g;
})();
}
renderLegacyDiagnostics();
</script>
""", encoding="utf-8")
from ui_skin import skin_report
temporary.write_text(skin_report(temporary.read_text(), 'activity'))
temporary.chmod(0o600)
temporary.replace(OUT)
print(f"apply={tot['apply']} letter={tot['letter']} chat={tot['chat']} giga={tot['giga']} err={tot['err']}")
print("->", OUT)
