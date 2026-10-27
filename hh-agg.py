"""Агрегирует исходные данные hh-data.json в раздел analysis файла statistics.json."""

from common import BASE, HH_CONFIG
import json
import re
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone

D = json.loads((BASE / 'hh-data.json').read_text(encoding="utf-8"))
rows = D["rows"]
now = datetime.now(timezone.utc)


def d(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ---- позиция -> категория ----
def cat_position(p):
    s = p.lower()
    if "1с" in s or "1c" in s or "erp" in s and "sap" not in s:
        return "1С / ERP"
    if any(w in s for w in ("bi", "dwh", "данных", "data ", "data-", "аналитик данных")):
        return "BI / DWH / данные"
    if "бизнес-анал" in s or "business anal" in s:
        return "Бизнес-аналитик"
    if any(w in s for w in ("ведущ", "senior", "lead", "главн", "старш", "sr.")):
        return "Senior / Lead СА"
    if any(w in s for w in ("junior", "младш", "стаж及", "стажёр", "стажер", "ученик")):
        return "Junior / стажёр"
    if "систем" in s and "анал" in s:
        return "Системный аналитик"
    if "анал" in s:
        return "Аналитик (прочее)"
    return "Прочее"


def norm_emp(e):
    e = re.sub(r"\s*\(.*?\)\s*", " ", e).strip()
    e = re.sub(r'^(ООО|АО|ПАО|ЗАО|ОАО|ГК|НПО|НПП|ФГУП|ГКУ)\s+', "", e, flags=re.I).strip()
    return e or "?"


state_map = {"response": "На рассмотрении", "invitation": "Приглашение", "interview": "Собеседование",
             "discard": "Отказ", "hidden": "Скрыт"}

total = len(rows)
by_state = Counter(state_map.get(r["state"], r["state"] or "?") for r in rows)
rejected = [r for r in rows if r["state"] == "discard"]
invited = [r for r in rows if r["state"] in ("invitation","interview")]
pending = [r for r in rows if r["state"] == "response"]

# работодатель ответил хоть что-то (кроме автоприветствий не отличить -> берём наличие сообщений работодателя)
employer_engaged = [r for r in rows if r["msgs_employer"] > 0]
# неотвеченные: работодатель написал последним И это не отказ/приглашение (т.е. висит вопрос)
unanswered = [r for r in rows if r["unanswered"] and r["state"] == "response"]


def q_kind(t):
    s = (t or "").lower()
    if "гигарекрут" in s or "max.ru" in s or "макс" in s and "интервью" in s:
        return "Скрининг-бот (Сбер / Макс)"
    if "к сожалению" in s and ("не готовы" in s or "не можем" in s):
        return "Фактически отказ"
    if any(w in s for w in ("ответьте", "вопрос", "уточн", "заполните", "анкет")):
        return "Вопросы работодателя"
    if any(w in s for w in ("рассмотрим", "свяжемся", "вернёмся", "вернемся", "ознаком")):
        return "Приняли, ждём решения"
    return "Другое"

# что слал бот
sent_letter = [r for r in rows if r["sent_ai_reply"]]
sent_contact = [r for r in rows if r["sent_contact"]]
sent_nothing = [r for r in rows if r["msgs_applicant"] == 0]

# --- отказы по работодателям ---
rej_emp = Counter(norm_emp(r["employer"]) for r in rejected)
# --- отказы по категориям позиций ---
rej_cat = Counter(cat_position(r["position"]) for r in rejected)
all_cat = Counter(cat_position(r["position"]) for r in rows)

# --- отказы: сколько было переписки перед отказом ---
rej_silent = len([r for r in rejected if r["msgs_employer"] == 0])   # отказ без единого сообщения
rej_afterchat = len([r for r in rejected if r["msgs_employer"] > 0])

# --- таймлайн по дням ---
days = {}
for r in rows:
    c = d(r["created_at"])
    if not c:
        continue
    k = c.date().isoformat()
    days.setdefault(k, {"sent": 0, "rej": 0, "inv": 0})
    days[k]["sent"] += 1
for r in rejected:
    u = d(r["updated_at"])
    if u:
        k = u.date().isoformat()
        days.setdefault(k, {"sent": 0, "rej": 0, "inv": 0})
        days[k]["rej"] += 1
for r in invited:
    u = d(r["updated_at"])
    if u:
        k = u.date().isoformat()
        days.setdefault(k, {"sent": 0, "rej": 0, "inv": 0})
        days[k]["inv"] += 1
timeline = [{"date": k, **v} for k, v in sorted(days.items())]

# --- неотвеченные: детали ---
def days_wait(r):
    u = d(r["updated_at"])
    return round((now - u).total_seconds() / 86400, 1) if u else None

unanswered_detail = sorted(
    [{
        "employer": norm_emp(r["employer"]),
        "position": r["position"],
        "kind": q_kind(r["last_text"] or r["last_employer_msg"]),
        "question": (r["last_text"] or r["last_employer_msg"] or "").strip().replace("\n", " ")[:200],
        "days": days_wait(r),
        "url": r["vacancy_url"],
    } for r in unanswered],
    key=lambda x: -(x["days"] or 0))
unanswered_kinds = Counter(x["kind"] for x in unanswered_detail)

# --- rejection rate по категориям ---
cat_rate = []
for c, n in all_cat.most_common():
    rj = rej_cat.get(c, 0)
    cat_rate.append({"cat": c, "total": n, "rej": rj,
                     "rate": round(100 * rj / n) if n else 0})

agg = {
    "generated_at": D["generated_at"],
    "total": total,
    "funnel": {
        "sent": total,
        "employer_engaged": len(employer_engaged),
        "invited": len(invited),
        "rejected": len(rejected),
        "pending": len(pending),
        "unanswered": len(unanswered),
    },
    "invited_total": len(invited),
    "by_state": dict(by_state),
    "rates": {
        "engaged_pct": round(100 * len(employer_engaged) / max(1, total)),
        "invite_pct": round(100 * len(invited) / max(1, total), 1),
        "reject_pct": round(100 * len(rejected) / max(1, total)),
        "reject_of_engaged_pct": round(100 * len(rejected) / max(1, len(employer_engaged))),
    },
    "rejections_by_employer": rej_emp.most_common(18),
    "rejections_by_category": cat_rate,
    "rejection_context": {"silent": rej_silent, "after_chat": rej_afterchat},
    "bot_activity": {
        "plain": len(sent_nothing),
        "with_letter_or_reply": len(sent_letter),
        "contact_sent": len(sent_contact),
    },
    "timeline": timeline,
    "unanswered_count": len(unanswered_detail),
    "unanswered_kinds": dict(unanswered_kinds),
    "unanswered": unanswered_detail[:60],
    "invited_list": [{"employer": norm_emp(r["employer"]), "position": r["position"]} for r in invited],
}
from statistics_store import publish
publish(BASE,"analysis",agg)
print(json.dumps({k: agg[k] for k in ("total", "funnel", "rates", "rejection_context", "bot_activity")},
                 ensure_ascii=False, indent=1))
print("\nОтказы по категориям:")
for c in cat_rate:
    print(f"  {c['cat']:<24} всего {c['total']:>3}  отказ {c['rej']:>3}  ({c['rate']}%)")
print("\nТоп отказов по работодателям:")
for e, n in rej_emp.most_common(12):
    print(f"  {n:>2}  {e}")
print(f"\nНеотвеченных: {len(unanswered_detail)}, приглашений: {len(invited)}")
print("Дни таймлайна:", len(timeline))
