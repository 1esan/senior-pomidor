"""Напомнить о себе в живых чатах (работодатель написал последним, отклик на рассмотрении).
  .venv/bin/python hh-bump16.py           -- показать
  .venv/bin/python hh-bump16.py --send    -- отправить
"""

from common import BASE, HH_CONFIG, hh_urlopen
from employer_guard import guard_negotiation, contact_reason, ContactBlocked
import json, sys, time, random, urllib.parse, urllib.request, urllib.error
from pathlib import Path

from common import hh_exchange
from candidate import load_profile
from runtime import operation_lock,save_json
DATA=json.loads((BASE/'hh-data.json').read_text())["rows"]
profile=load_profile()
MSGS=[f"Здравствуйте! По-прежнему заинтересован в позиции, готов обсудить детали. Контакты: Telegram {profile['telegram']}, телефон {profile['phone']}."]
DONE=BASE/'.state/hh-bumped.json'
done=set(json.loads(DONE.read_text())) if DONE.exists() else set()

def post(nid,msg):
    # Snapshot selects candidates; live state decides whether they still qualify.
    guard_negotiation(nid,lambda method,path:hh_exchange(method,path))
    page=0;messages=[]
    while True:
        code,data=hh_exchange('GET',f'/negotiations/{nid}/messages?page={page}')
        messages.extend(data.get('items',[]))
        if page+1>=data.get('pages',1):break
        page+=1
    last=max(messages,key=lambda m:(m.get('created_at') or '',str(m.get('id') or ''))) if messages else None
    if not last or (last.get('author') or {}).get('participant_type')!='employer':raise ContactBlocked('Работодатель больше не последний в чате')
    code,_=hh_exchange('POST',f'/negotiations/{nid}/messages',{'message':msg})
    return code

targets = [r for r in DATA if r["state"] == "response" and r["unanswered"]
           and not contact_reason({"employer":{"name":r.get("employer")}, "name":r.get("position"), "description":r.get("last_employer_msg")})]
print(f"Живых чатов: {len(targets)}")
for r in targets:
    print(f"  {r['employer'][:30]:<30} {r['position'][:44]}")

def send_all():
    print()
    todo = [r for r in targets if r["id"] not in done]
    print(f"осталось отправить: {len(todo)}")
    for i, r in enumerate(todo):
        try:
            code = post(r["id"], random.choice(MSGS))
        except ContactBlocked as ex:
            print(f"  {r['id']}: контакт заблокирован — {ex}")
            continue
        print(f"  [{code}] {r['employer'][:40]}")
        if isinstance(code, int) and code in (200, 201, 204):
            done.add(r["id"])
            save_json(DONE,list(done))
        if i + 1 < len(todo):
            time.sleep(random.uniform(28, 42))
    print("готово")

if "--send" in sys.argv:
    with operation_lock("hh"):send_all()
