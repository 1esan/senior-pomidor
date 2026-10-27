"""Единые условия вакансий: отправка, пропуск или ручное уточнение. Без сети."""
import re,html
from decimal import Decimal, InvalidOperation
from employer_guard import contact_reason



# Only the vacancy title defines seniority: descriptions may mention mentoring juniors.
_ENTRY_LEVEL_TITLE = re.compile(
    r"\b(?:младш[а-я]*|начинающ[а-я]*|стаж[её]р[а-я]*|стажиров[а-я]*|"
    r"ученик[а-я]*|учениц[а-я]*|ученическ[а-я]*|apprentice(?:ship)?|"
    r"джун(?:иор)?[а-я]*|джуниор[а-я]*|junior|jr|intern(?:ship)?|trainee|graduate)\b"
    r"|\bentry[\s‐‑–—-]*level\b"
    r"|\bмолод(?:ой|ая|ые|ого|ому)\s+специалист[а-я]*\b"
    r"|\bбез\s+(?:опыта|опыт[а-я]*\s+работы)\b",
    re.IGNORECASE,
)


def entry_level_reason(vacancy):
    title = html.unescape(str(vacancy.get('name') or ''))
    if match := _ENTRY_LEVEL_TITLE.search(title):
        return f'Начальный уровень исключён: «{match.group(0)}» в названии «{title}»'
    return None


def vacancy_decision(vacancy, profile):
    """Неясные условия и переезд требуют решения человека, а не автоотклика."""
    if reason := contact_reason(vacancy, profile):
        return "skip", reason
    description=html.unescape(re.sub(r'<[^>]+>',' ',vacancy.get('description') or ''))
    tk=bool(re.search(r'\bТК(?:\s+РФ)?\b|трудов[а-я]*\s+(?:договор|кодекс)',description,re.I))
    non_tk=bool(re.search(r'(?:оформл[а-я]*|сотрудничество|договор|работ[а-я]*)[^.!\n]{0,60}(?:ГПХ|самозанят[а-я]*|(?:на|через|как)\s+ИП)',description,re.I))
    tk_refused=bool(re.search(r'(?:не|без)[^.!\n]{0,20}(?:ТК|трудов[а-я]*\s+договор)',description,re.I))
    if profile.get('employment_types')==['ТК РФ'] and non_tk and (not tk or tk_refused):
        return 'skip','Указано оформление вне ТК РФ'
    if profile.get('business_travel') is False and re.search(r'готовност[а-я]*[^.!\n]{0,25}командиров|(?:регулярн[а-я]*|част[а-я]*)\s+командиров',description,re.I):
        return 'skip','Указаны обязательные командировки'
    formats = {f.get("id") for f in (vacancy.get("work_format") or [])}
    remote = "REMOTE" in formats or (vacancy.get("schedule") or {}).get("id") == "remote"
    office = "ON_SITE" in formats or "HYBRID" in formats or (vacancy.get("schedule") or {}).get("id") == "fullDay"
    allowed = set(profile.get("work_formats", []))
    city = (vacancy.get("area") or {}).get("name", "").strip().casefold()
    cities = profile.get("office_cities", [])
    if isinstance(cities, str):
        cities = [cities]
    cities = {c.strip().casefold() for c in cities}
    if remote and "Удалёнка" in allowed:
        pass
    elif office and (("ON_SITE" in formats and "Офис" in allowed) or ("HYBRID" in formats and "Гибрид" in allowed) or not formats and "Офис" in allowed):
        if not city:
            return "review", "Не указан город офиса/гибрида"
        if city not in cities:
            if profile.get("mobility"):
                return "review", f"Переезд в {city}: условия нужно согласовать"
            return "skip", f"Офис/гибрид вне разрешённых городов: {city}"
    elif formats or remote:
        return "skip", "Формат работы не соответствует профилю"
    else:
        return "review", "Не указан однозначный формат работы"

    max_days=profile.get('hybrid_office_days_max')
    if 'HYBRID' in formats and not remote and max_days is not None:
        patterns=[r'([0-5])\s*(?:дня|дней|день)[^.!\n]{0,25}в\s+офисе',r'(?:в\s+офисе|офис)[^.!\n]{0,12}([0-5])\s*(?:дня|дней|день)']
        counts=[int(m.group(1)) for pattern in patterns for m in re.finditer(pattern,description,re.I)]
        if counts and max(counts)>max_days:return 'skip','Гибрид требует больше разрешённых офисных дней'
    if profile.get("employment_types")==["ТК РФ"] and not tk:
        return "review","Оформление по ТК РФ не подтверждено"

    salary = vacancy.get("salary_range") or vacancy.get("salary")
    if not salary:
        return "review", "Зарплата не указана; нужно подтвердить вилку"
    if salary.get("currency") not in ("RUR", "RUB"):
        return "review", "Зарплата в другой валюте: требуется согласование"
    mode = (salary.get("mode") or {}).get("id")
    if mode and mode != "MONTH":
        return "review", "Оплата не за месяц: требуется согласование"
    minimum = Decimal(str(profile["salary_min"]))
    try:
        low = Decimal(str(salary["from"])) if salary.get("from") is not None else None
        high = Decimal(str(salary["to"])) if salary.get("to") is not None else None
        if any(x is not None and not x.is_finite() for x in (low, high)):
            return "review", "Некорректные значения зарплаты"
    except InvalidOperation:
        return "review", "Некорректные значения зарплаты"
    if low is not None and high is not None and low > high:
        return "review", "Некорректная зарплатная вилка"
    if high is not None and high < minimum:
        return "skip", "Верхняя граница зарплаты ниже требуемого минимума"
    if salary.get("gross") is not False:
        return "review", "Зарплата до налогов или база не указана: нужна сумма на руки"
    if high is not None and high >= minimum or low is not None and low >= minimum:
        return "allow", "Формат, город и зарплата соответствуют профилю"
    return "review", "Не подтверждена возможность зарплаты от требуемого минимума"


def application_decision(vacancy, profile):
    """Широкий поиск технических интервью: условия обсуждаются после отклика.

    Только для новых откликов HH. Анкета и политика интервью не меняются.
    Запреты компаний остаются обязательными.
    """
    if reason := contact_reason(vacancy, profile):
        return "skip", reason
    if reason := entry_level_reason(vacancy):
        return "skip", reason
    return "allow", "Широкий поиск: зарплата, оформление, город и формат не ограничивают отклик"
