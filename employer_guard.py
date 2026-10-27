"""Запрет контактов с работодателями из резюме. Все решения без ИИ."""
import html
import re
import unicodedata
from difflib import SequenceMatcher
from candidate import load_profile


class ContactBlocked(RuntimeError):
    pass


def normalize(text):
    # Кириллица, латиница, смешанные символы и пробелы/дефисы сравниваются одинаково.
    text = unicodedata.normalize("NFKC", html.unescape(str(text or ""))).casefold()
    text = re.sub(r"<[^>]*>", " ", text)
    table = dict(zip("абвгдежзийклмнопрстуфхцчшщыэюяёьъ", ["a","b","v","g","d","e","zh","z","i","i","k","l","m","n","o","p","r","s","t","u","f","h","ts","ch","sh","sch","y","e","yu","ya","e",""," "]))
    return "".join(table.get(c,c) for c in text)


def excluded_ids(profile):
    return sorted({str(i) for group in profile.get("excluded_employers",[]) for i in group.get("hh_ids",[])})


def blocked_text_reason(text, profile):
    normalized=normalize(text)
    words=re.findall(r"[a-z0-9]+",normalized)
    compact="".join(words)
    for group in profile.get("excluded_employers",[]):
        for alias in group.get("aliases",[]):
            a=re.sub(r"[^a-z0-9]","",normalize(alias))
            if a and a in compact:
                return f"Запрещённая/схожая компания: {group['company']} (совпадение {alias})"
            if len(a)>=5 and any(abs(len(w)-len(a))<=1 and SequenceMatcher(None,a,w).ratio()>=0.80 for w in words):
                return f"Подозрение на запрещённую компанию: {group['company']} (схожее написание)"
    ids=set(excluded_ids(profile))
    for eid in re.findall(r"(?:employer/|employer_id[=:]\s*)(\d+)",str(text or ""),re.I):
        if eid in ids:return f"Запрещённый HH ID в тексте: {eid}"
    return None


def contact_reason(vacancy, profile=None, context=""):
    profile=load_profile() if profile is None else profile
    if not profile.get("employer_contact_policy",{}).get("strict") or not profile.get("excluded_employers"):
        return "Нет подтверждённого списка запретов; контакт остановлен"
    employer=vacancy.get("employer") or {}
    eid=str(employer.get("id") or "")
    if eid and eid in excluded_ids(profile):return f"Запрещённый работодатель: HH ID {eid}"
    text="\n".join(str(x or "") for x in [employer.get("name"),employer.get("alternate_url"),vacancy.get("name"),vacancy.get("description"),vacancy.get("alternate_url"),context])
    if reason:=blocked_text_reason(text,profile):return reason
    name=str(employer.get("name") or "").strip()
    compact_name=re.sub(r"[^a-z0-9]","",normalize(name))
    if not re.search(r"[a-z]",compact_name) or compact_name in {"unknown","confidential","neizvestno","neukazano","neukazana","neizvestnayakompaniya","neizvestnyirabotodatel","kompaniya","rabotodatel"}:
        return "Работодатель не установлен; контакт остановлен"
    if re.search(r"наш(?:его|ему)? клиент|для клиента|имя заказчика не|конфиденциальн(?:ый|ая) (?:клиент|компания)|крупн(?:ый|ого) (?:банк|заказчик)|кадров(?:ое|ого) агентств",text,re.I):
        return "Возможен скрытый заказчик/агентство; контакт требует ручной проверки"
    return None


def ensure_contact(vacancy, profile=None, context=""):
    if reason:=contact_reason(vacancy,profile,context):raise ContactBlocked(reason)


def ensure_full_contact(vacancy, fetch, context=""):
    # Сначала запрет по уже известным сведениям; потом свежая полная вакансия.
    ensure_contact(vacancy,context=context)
    vid=vacancy.get("id")
    if not vid:raise ContactBlocked("Нет ID вакансии для проверки адресата")
    full=fetch(f"/vacancies/{vid}")
    if not isinstance(full,dict) or str(full.get("id") or "")!=str(vid):
        raise ContactBlocked("Полная вакансия не подтверждена; контакт остановлен")
    ensure_contact(full,context=context)
    return full


def guard_negotiation(nid, api):
    """Финальная проверка адресата перед рассылкой; ошибки чтения запрещают отправку."""
    def get(path):
        code,data=api("GET",path)
        if code!=200:raise ContactBlocked(f"Адресат не проверен: HTTP {code}")
        return data
    page=0;neg=None
    while True:
        data=get(f"/negotiations?page={page}&per_page=100&status=active")
        neg=next((n for n in data.get("items",[]) if str(n.get("id"))==str(nid)),None)
        if neg or page+1>=data.get("pages",1):break
        page+=1
    if neg is None:raise ContactBlocked("Активный чат не найден; отправка остановлена")
    full=ensure_full_contact(neg.get("vacancy") or {},get)
    page=0
    while True:
        messages=get(f"/negotiations/{nid}/messages?page={page}")
        context="\n".join(m.get("text") or "" for m in messages.get("items",[]) if (m.get("author") or {}).get("participant_type")=="employer")
        ensure_contact(full,context=context)
        if page+1>=messages.get("pages",1):break
        page+=1
    return full


def extract_company(text):
    match=re.search(r"(?:^|\n)\s*(?:компания|работодатель|организация)\s*[:—-]\s*([^\n]+)",str(text or ""),re.I)
    return match.group(1).strip() if match else None
