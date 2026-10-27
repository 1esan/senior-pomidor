"""
Собирает свежие данные по откликам hh.ru и пересобирает дашборд hh-dashboard.html.

  py hh-dash.py           -- быстро (~15 c): воронка, отказы, таймлайн, приглашения
  py hh-dash.py --full    -- + неотвеченные чаты и что слал бот (~15-20 мин, перебирает переписку)
"""

from common import BASE, HH_CONFIG, hh_read_json
import json, re, sys, time, html as _html
import urllib.parse, urllib.request, urllib.error
import hashlib
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone

CONFIG = HH_CONFIG / 'auth.json'
UA = "hh-dash/1.0"
API = "https://api.hh.ru"
OUT = BASE / "hh-dashboard.html"
TEMPLATE = BASE / "hh-dash-template.html"

from candidate import load_profile
MARK = load_profile().get("telegram") or "\x00"
FROM_ANALYSIS = "--from-analysis" in sys.argv
FULL = "--full" in sys.argv or FROM_ANALYSIS
ANALYSIS = json.loads((BASE / "hh-data.json").read_text()) if FROM_ANALYSIS else None
MESSAGES = json.loads((BASE / ".state/report-messages.json").read_text()) if FROM_ANALYSIS else None
if FROM_ANALYSIS:
    assert ANALYSIS.get("complete") and ANALYSIS["generated_at"] == MESSAGES["generated_at"], "Анализ и переписка должны быть из одного снимка"


def api(path):
    return hh_read_json(path)


def all_negotiations():
    if FROM_ANALYSIS:
        for r in ANALYSIS['rows']:
            yield {'id': r['id'], 'state': {'id':r['state']}, 'vacancy':{'name':r['position'], 'employer':{'name':r['employer']}, 'alternate_url':r['vacancy_url']}, 'created_at':r['created_at'], 'updated_at':r['updated_at']}
        return
    for status in ("active", "archived"):
        page = 0
        while True:
            d = api(f"/negotiations?page={page}&per_page=100&status={status}")
            items = d.get("items", [])
            if not items:
                break
            yield from items
            if page + 1 >= d.get("pages", 1):
                break
            page += 1
            time.sleep(0.2)


def last_msg(nid):
    if FROM_ANALYSIS:
        records = MESSAGES['messages'].get(str(nid), [])
        text_records = [m for m in records if (m.get('text') or '').strip()]
        last = max(text_records, key=lambda m:m.get('at') or '') if text_records else None
        return ((last['who'],last['text']) if last else None), [m['text'] for m in text_records if m['who']=='applicant'], [m['text'] for m in text_records if m['who']=='employer']
    page = 0
    last = None
    records = []
    appl_txt, empl_txt = [], []
    while True:
        d = api(f"/negotiations/{nid}/messages?page={page}")
        for m in d.get("items", []):
            if not (m.get("text") or "").strip():
                continue
            who = (m.get("author") or {}).get("participant_type")
            (appl_txt if who == "applicant" else empl_txt).append(m["text"])
            records.append((m.get("created_at") or "", str(m.get("id") or ""), who, m["text"]))
        if page + 1 >= d.get("pages", 1):
            break
        page += 1
        time.sleep(0.1)
    if records:
        newest = max(records, key=lambda r: (r[0], r[1]))
        last = (newest[2], newest[3])
    return last, appl_txt, empl_txt


def cat_position(p):
    s = p.lower()
    if "1с" in s or "1c" in s or "erp" in s:
        return "1С / ERP"
    if any(w in s for w in ("bi", "dwh", "данных", "data ", "data-")):
        return "BI / DWH / данные"
    if "бизнес-анал" in s or "business anal" in s:
        return "Бизнес-аналитик"
    if any(w in s for w in ("ведущ", "senior", "lead", "главн", "старш", "sr.")):
        return "Senior / Lead СА"
    if any(w in s for w in ("junior", "младш", "стаж", "ученик")):
        return "Junior / стажёр"
    if "систем" in s and "анал" in s:
        return "Системный аналитик"
    if "анал" in s:
        return "Аналитик (прочее)"
    return "Прочее"


def norm_emp(e):
    e = re.sub(r"\s*\(.*?\)\s*", " ", e).strip()
    e = re.sub(r"^(ООО|АО|ПАО|ЗАО|ОАО|ГК|НПО|НПП|ФГУП|ГКУ)\s+", "", e, flags=re.I).strip()
    return e or "?"


def q_kind(t):
    s = (t or "").lower()
    if "гигарекрут" in s or "max.ru" in s:
        return "Скрининг Сбера"
    if "к сожалению" in s and ("не готовы" in s or "не можем" in s):
        return "Фактически отказ"
    if any(w in s for w in ("ответьте", "вопрос", "уточн", "заполните", "тестов")):
        return "Вопрос работодателя"
    if any(w in s for w in ("рассмотрим", "свяжемся", "вернёмся", "вернемся", "ознаком")):
        return "Ждут решения"
    return "Другое"


def main():
    t0 = time.time()
    rows = []
    print("Загружаю отклики...")
    for neg in all_negotiations():
        v = neg.get("vacancy") or {}
        rows.append({
            "id": neg["id"],
            "vacancy_id": v.get("id"),
            "employer_id": (v.get("employer") or {}).get("id"),
            "state": (neg.get("state") or {}).get("id"),
            "employer": (v.get("employer") or {}).get("name", "") or "?",
            "position": v.get("name", ""),
            "url": v.get("alternate_url", ""),
            "created": neg.get("created_at"),
            "updated": neg.get("updated_at"),
        })
    # дедуп
    seen = set(); rows = [r for r in rows if not (r["id"] in seen or seen.add(r["id"]))]
    total = len(rows)
    print(f"  {total} откликов за {time.time()-t0:.0f} c")

    def dparse(s):
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None

    rejected = [r for r in rows if r["state"] == "discard"]
    invited = [r for r in rows if r["state"] in ("invitation","interview")]
    pending = [r for r in rows if r["state"] == "response"]

    rej_emp = Counter(norm_emp(r["employer"]) for r in rejected)
    inv_emp = Counter(norm_emp(r["employer"]) for r in invited)
    all_cat = Counter(cat_position(r["position"]) for r in rows)
    rej_cat = Counter(cat_position(r["position"]) for r in rejected)
    cat_rate = [{"cat": c, "total": n, "rej": rej_cat.get(c, 0),
                 "rate": round(100 * rej_cat.get(c, 0) / n) if n else 0}
                for c, n in all_cat.most_common()]

    ST = {"invitation": 1, "interview": 1, "discard": 2, "response": 3}  # inv, rej, pend

    def split(items, keyfn):
        d = {}
        for r in items:
            s = d.setdefault(keyfn(r), [0, 0, 0, 0])  # total, inv, rej, pend
            s[0] += 1
            i = ST.get(r["state"])
            if i:
                s[i] += 1
        return d

    emp_split = split(rows, lambda r: norm_emp(r["employer"]))
    top_emp = sorted(emp_split.items(), key=lambda kv: -kv[1][0])[:20]
    cat_split = split(rows, lambda r: cat_position(r["position"]))
    cat_bars = sorted(([c, *v] for c, v in cat_split.items()), key=lambda x: -x[1])

    days = {}
    for r in rows:
        c = dparse(r["created"])
        if c:
            days.setdefault(c.date().isoformat(), {"sent": 0, "rej": 0, "inv": 0})["sent"] += 1
    for r in rejected + invited:
        u = dparse(r["updated"])
        if u:
            k = days.setdefault(u.date().isoformat(), {"sent": 0, "rej": 0, "inv": 0})
            k["rej" if r["state"] == "discard" else "inv"] += 1
    timeline = [{"date": k, **v} for k, v in sorted(days.items())]

    sber = [r for r in rows if re.search(r"сбер|sber", r["employer"], re.I)]
    sber_inv = sum(1 for r in sber if r["state"] in ("invitation","interview"))
    sber_rej = sum(1 for r in sber if r["state"] == "discard")

    data = {
        "gen": ANALYSIS["generated_at"] if FROM_ANALYSIS else datetime.now(timezone.utc).isoformat(),
        "mode": "full" if FULL else "fast",
        "funnel": {"sent": total, "invited": len(invited), "rejected": len(rejected),
                   "pending": len(pending), "other": total-len(pending)-len(invited)-len(rejected)},
        "rates": {"invite_pct": round(100 * len(invited) / total, 1) if total else 0,
                  "reject_pct": round(100 * len(rejected) / total) if total else 0},
        "sber": {"apps": len(sber), "inv": sber_inv, "rej": sber_rej,
                 "inv_pct": round(100 * sber_inv / len(sber)) if sber else 0,
                 "rest_inv_pct": round(100 * (len(invited) - sber_inv) / max(1, total - len(sber)), 1)},
        "cats": cat_rate,
        "rej_emps": rej_emp.most_common(14),
        "inv_emps": inv_emp.most_common(10),
        "top_emp": top_emp,          # [name, [total, inv, rej, pend]]
        "cat_bars": cat_bars,        # [cat, total, inv, rej, pend]
        "uniq_emp": len(emp_split),
        "timeline": timeline,
    }

    # ---- тяжёлые данные ----
    snapshot = hashlib.sha256(json.dumps(sorted((r["id"], r["state"], r["updated"]) for r in rows), ensure_ascii=False).encode()).hexdigest()
    from statistics_store import read_statistics
    heavy = (read_statistics(BASE).get('dashboard') or {}).get('heavy') or {}
    if heavy.get('snapshot') != snapshot:
        heavy = {}
    if FULL:
        print("Разбираю переписку (долго)...")
        un, bot_plain, bot_ai, bot_contact = [], 0, 0, 0
        for i, r in enumerate(rows):
            last, appl, empl = last_msg(r["id"])
            if not FROM_ANALYSIS: time.sleep(0.12)
            if not appl:
                bot_plain += 1
            if any(MARK in x for x in appl):
                bot_contact += 1
            if any(len(x) > 40 and MARK not in x or MARK in x and len(x) > 130 for x in appl):
                bot_ai += 1
            waiting = bool(last and last[0] == "employer")
            info = next((x for x in ANALYSIS['rows'] if str(x['id'])==str(r['id'])),{}) if FROM_ANALYSIS else {}
            if FROM_ANALYSIS: waiting=bool(info.get('unanswered',waiting))
            if r["state"] == "response" and waiting:
                u = dparse(r["updated"])
                un.append({"e": norm_emp(r["employer"]), "p": r["position"],
                           "k": q_kind((info.get("last_text") or info.get("last_employer_msg") or (last[1] if last else ""))),
                           "d": round((datetime.now(timezone.utc) - u).total_seconds() / 86400, 1) if u else 0})
            if (i + 1) % 50 == 0:
                print(f"  {i+1}/{total}")
        un.sort(key=lambda x: -x["d"])
        heavy = {
            "un_count": len(un),
            "un": un[:40],
            "un_kinds": dict(Counter(x["k"] for x in un)),
            "bot": {"plain": bot_plain, "ai": bot_ai, "contact": bot_contact},
            "gen": data["gen"],
            "snapshot": snapshot,
        }
    data["heavy"] = heavy

    from application_status import publish_snapshot
    publish_snapshot(BASE,rows,data["gen"],observed_since=None if FROM_ANALYSIS else t0)
    tpl = TEMPLATE.read_text(encoding="utf-8")
    from statistics_store import publish
    publish(BASE,"dashboard",data)
    encoded = "{}"
    temporary = OUT.with_suffix(".html.tmp")
    temporary.write_text(tpl.replace("__DATA__", encoded), encoding="utf-8")
    from ui_skin import skin_report
    temporary.write_text(skin_report(temporary.read_text(), 'dashboard'))
    temporary.chmod(0o600)
    temporary.replace(OUT)
    print(f"\nГотово за {time.time()-t0:.0f} c -> {OUT}")


if __name__ == "__main__":
    main()
