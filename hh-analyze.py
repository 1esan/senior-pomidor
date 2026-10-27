"""
Собирает данные по всем откликам hh.ru в JSON для дашборда.
  py hh-analyze.py  ->  пишет hh-data.json рядом
"""

from common import BASE, HH_CONFIG, hh_read_json
import json
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone

CONFIG = HH_CONFIG / 'auth.json'
UA = "hh-analyze/1.0"
API = "https://api.hh.ru"
OUT = Path(__file__).with_name("hh-data.json")
from candidate import load_profile
MARK = load_profile().get("telegram") or "\x00"


def api(path):
    return hh_read_json(path)


def all_negotiations():
    for status in ("active", "archived"):
        page = 0
        while True:
            d = api(f"/negotiations?page={page}&per_page=100&status={status}")
            items = d.get("items", [])
            if not items:
                break
            for it in items:
                it["_status_group"] = status
                yield it
            if page + 1 >= d.get("pages", 1):
                break
            page += 1
            time.sleep(0.25)


def messages(nid):
    out = []
    page = 0
    while True:
        d = api(f"/negotiations/{nid}/messages?page={page}")
        for m in d.get("items", []):
            out.append({
                "who": (m.get("author") or {}).get("participant_type"),
                "text": m.get("text") or "",
                "at": m.get("created_at"),
            })
        if page + 1 >= d.get("pages", 1):
            break
        page += 1
        time.sleep(0.1)
    return sorted(out, key=lambda m: m.get("at") or "")


def main():
    rows = []
    message_cache = {}
    seen = set()
    # Новый снимок: известные ID не пропускаются между запусками.
    def flush():
        temporary = OUT.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(
            {"generated_at": datetime.now(timezone.utc).isoformat(),
             "complete": True, "count": len(rows), "rows": rows},
            ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(OUT)

    n = len(rows)
    for neg in all_negotiations():
        nid = neg["id"]
        if nid in seen:
            continue
        seen.add(nid)
        n += 1
        vac = neg.get("vacancy") or {}
        emp = (vac.get("employer") or {}).get("name", "") or "?"
        msgs = messages(nid)
        message_cache[str(nid)] = msgs
        time.sleep(0.15)
        appl = [m for m in msgs if m["who"] == "applicant"]
        empl = [m for m in msgs if m["who"] == "employer"]
        appl_txt = [m for m in appl if m["text"].strip()]
        last = msgs[-1] if msgs else None
        # классификация наших сообщений
        sent_contact = any(MARK in m["text"] for m in appl_txt)
        sent_ai = any(len(m["text"]) > 40 and MARK not in m["text"] for m in appl_txt) or \
                  any(MARK in m["text"] and len(m["text"]) > 130 for m in appl_txt)
        # последний вопрос работодателя
        last_emp = next((m["text"] for m in reversed(empl) if m["text"].strip()), "")
        rows.append({
            "id": nid,
            "state": (neg.get("state") or {}).get("id"),
            "state_name": (neg.get("state") or {}).get("name"),
            "status_group": neg.get("_status_group"),
            "employer": emp,
            "position": vac.get("name", ""),
            "vacancy_url": vac.get("alternate_url", ""),
            "created_at": neg.get("created_at"),
            "updated_at": neg.get("updated_at"),
            "has_updates": neg.get("has_updates"),
            "decline_allowed": neg.get("decline_allowed"),
            "msgs_total": len(msgs),
            "msgs_applicant": len(appl_txt),
            "msgs_employer": len([m for m in empl if m["text"].strip()]),
            "last_author": last["who"] if last else None,
            "last_text": (last["text"][:280] if last else ""),
            "last_employer_msg": last_emp[:400],
            "sent_contact": sent_contact,
            "sent_ai_reply": bool(sent_ai),
            "unanswered": bool(empl) and last and last["who"] == "employer",
        })
        if n % 20 == 0:
            print(f"  {n}...",flush=True)

    flush()
    from runtime import save_json
    save_json(BASE / ".state/report-messages.json", {"generated_at": json.loads(OUT.read_text())["generated_at"], "messages": message_cache})
    print(f"\nГотово: {len(rows)} откликов -> {OUT}")


if __name__ == "__main__":
    main()
