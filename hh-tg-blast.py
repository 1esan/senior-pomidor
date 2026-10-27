"""
Разовая рассылка контакта (телеграм + телефон) во все активные чаты hh.ru,
где этого сообщения ещё не было. Повторный запуск не дублирует.

  py hh-tg-blast.py            -- показать, куда бы отправил
  py hh-tg-blast.py --send     -- реально отправить
"""

from common import BASE, HH_CONFIG, hh_urlopen
from employer_guard import guard_negotiation, contact_reason, ContactBlocked
import json
import sys
import time
import datetime
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

from common import hh_exchange
from candidate import load_profile
from runtime import operation_lock
p=load_profile()
MARK=p['telegram']
MESSAGES=[f"Здравствуйте! Для связи: Telegram {p['telegram']}, телефон {p['phone']}. Готов обсудить вакансию."]

COOLDOWN = 30  # секунд между отправками (--cooldown N чтобы поменять)
LIMIT = None   # максимум отправок за запуск (--limit N)


def api(method,path,form=None):
    return hh_exchange(method,path,form)


def all_negotiations():
    page = 0
    while True:
        code, d = api("GET", f"/negotiations?page={page}&per_page=100&status=active")
        if code!=200:raise RuntimeError("Не удалось прочитать отклики")
        items = d.get("items", [])
        if not items:
            return
        yield from items
        if page + 1 >= d.get("pages", 1):
            return
        page += 1
        time.sleep(0.3)


def already_sent(nid):
    page = 0
    while True:
        code, d = api("GET", f"/negotiations/{nid}/messages?page={page}")
        if code!=200:raise RuntimeError("Не удалось проверить переписку")
        for m in d.get("items", []):
            if (m.get("author") or {}).get("participant_type") == "applicant" \
               and MARK in (m.get("text") or ""):
                return True
        if page + 1 >= d.get("pages", 1):
            return False
        page += 1
        time.sleep(0.15)


def _arg(name, default):
    for a in sys.argv:
        if a.startswith(name + "="):
            return int(a.split("=", 1)[1])
    return default


def main():
    send = "--send" in sys.argv
    cooldown = _arg("--cooldown", COOLDOWN)
    limit = _arg("--limit", LIMIT or 10**9)
    days = _arg("--days", 0)  # 0 = все; N = только отклики за последние N дней
    cutoff = None
    if days:
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)

    todo = []
    for neg in all_negotiations():
        if (neg.get("state") or {}).get("id") in ("discard", "discard_by_applicant"):
            continue
        if cutoff:
            try:
                ca = datetime.datetime.fromisoformat(neg.get("created_at", "").replace("Z", "+00:00"))
                if ca < cutoff:
                    continue
            except ValueError:
                pass
        nid = neg["id"]
        vac = neg.get("vacancy") or {}
        emp = (vac.get("employer") or {}).get("name", "")
        if reason := contact_reason(vac):
            print(f"Контакт исключён: {emp} — {reason}")
            continue
        time.sleep(0.2)
        if already_sent(nid):
            continue
        todo.append((nid, vac.get("name", ""), emp))

    print(f"\nЧатов без контакта: {len(todo)}")
    for nid, name, emp in todo[:80]:
        print(f"  {name}  --  {emp}")
    if len(todo) > 80:
        print(f"  ... ещё {len(todo) - 80}")

    if send and todo:
        batch = todo[:limit]
        print(f"\nОтправляю {len(batch)} (кулдаун {cooldown}с, ~{len(batch)*cooldown//60} мин)")
        ok = 0
        for i, (nid, *_ ) in enumerate(batch):
            msg = random.choice(MESSAGES)
            try:
                code, resp = api("POST", f"/negotiations/{nid}/messages", {"message": msg})
            except ContactBlocked as ex:
                print(f"  {nid}: контакт заблокирован — {ex}")
                continue
            resp = resp if isinstance(resp, dict) else {}
            if code in (200, 201, 204):
                ok += 1
            else:
                print(f"  {nid}: HTTP {code} {resp.get('errors') or resp}")
            if i + 1 < len(batch):
                time.sleep(cooldown)
        print(f"\nОтправлено: {ok} из {len(batch)}  (осталось без контакта: {len(todo) - len(batch)})")


if __name__ == "__main__":
    with operation_lock("hh"):main()
