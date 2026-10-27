"""Аудит вакансий по текущему giga_profile.json. Переезд и неясные условия — на согласование.
Отзыв только явных несоответствий через --withdraw и ручное подтверждение.
"""
from common import BASE, HH_CONFIG, hh_urlopen
from candidate import load_profile
from vacancy_policy import vacancy_decision
from employer_guard import contact_reason
import json
import re
import sys
import time
from pathlib import Path
import urllib.request
import urllib.error

from common import hh_exchange
from runtime import operation_lock
def api(method,path):return hh_exchange(method,path)


def all_negotiations():
    page = 0
    while True:
        code, data = api("GET", f"/negotiations?page={page}&per_page=100")
        if code != 200:
            raise RuntimeError(f"Ошибка чтения откликов: HTTP {code}")
        items = data.get("items", [])
        if not items:
            return
        yield from items
        if page + 1 >= data.get("pages", 1):
            return
        page += 1
        time.sleep(0.3)


def main():
    args = set(sys.argv[1:])
    withdraw = "--withdraw" in args
    if args - {"--withdraw"}:
        raise SystemExit("Доступен только --withdraw; условия берутся из профиля")
    profile = load_profile()

    flagged = []
    review = []
    forbidden = []
    checked = 0
    for neg in all_negotiations():
        if neg.get("state", {}).get("id") in ("discard", "discard_by_applicant"):
            continue
        vac = neg.get("vacancy") or {}
        vid = vac.get("id")
        if not vid:
            continue
        checked += 1
        emp = (vac.get("employer") or {}).get("name", "")
        code, full = api("GET", f"/vacancies/{vid}")
        if code != 200:
            raise RuntimeError(f"Не удалось проверить вакансию {vid}: HTTP {code}")
        time.sleep(0.22)
        area = full.get("area") or {}
        city = area.get("name") or ""
        fmt = "/".join(f.get("name", "") for f in (full.get("work_format") or []))
        if blocked := contact_reason(full, profile):
            forbidden.append((neg["id"], emp, blocked))
            continue  # Не предлагать отзыв и не взаимодействовать с запрещённым работодателем.
        decision, reason = vacancy_decision(full, profile)
        if decision == "review":
            review.append((neg["id"], vac.get("name", ""), emp, city, fmt, reason))
        if decision == "allow":
            reason = None
        if decision == "skip":
            flagged.append((neg["id"], vac.get("name", ""), emp, city, fmt, reason))

    print(f"\nПроверено активных откликов: {checked}")
    print("Условия: текущий подтверждённый профиль; строгие запреты работодателей действуют")
    print(f"На согласование (не отзываются): {len(review)}")
    for nid, name, emp, city, fmt, reason in review:
        print(f"  [{nid}] {reason} | {name} -- {emp}")
    print(f"Запрещённые компании — никаких действий: {len(forbidden)}")
    print(f"На отзыв: {len(flagged)}\n")
    for nid, name, emp, city, fmt, reason in flagged:
        print(f"  [{nid}] {reason:<32} | {fmt:<18} | {name}  --  {emp}")

    if withdraw and flagged:
        ans = input(f"\nОтозвать эти {len(flagged)} откликов? (да/нет): ").strip().lower()
        if ans in ("да", "д", "y", "yes"):
            for nid, *_ in flagged:
                code, _ = api("DELETE", f"/negotiations/{nid}")
                print(f"  отзыв {nid}: HTTP {code}")
                time.sleep(0.4)
            print("Готово.")
        else:
            print("Отменено.")


if __name__ == "__main__":
    with operation_lock("hh"):main()
