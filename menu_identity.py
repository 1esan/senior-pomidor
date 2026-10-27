"""Disambiguate numbered menu items using verified public vacancy identity."""
import re
from urllib.parse import urlsplit

def exact_menu_button(buttons,scope,bubble):
    from autonomous_runtime import NeedsDecision
    identity=scope['menu_identity']
    if not bubble:raise NeedsDecision('Нужно проверить ссылки и описание текущего меню')
    expected=urlsplit(identity['official_url'])
    def same_url(raw):
        parsed=urlsplit(raw)
        return parsed.scheme=='https' and parsed.hostname==expected.hostname and bool(re.search(r'(?:/|-)' + re.escape(identity['official_id']) + r'/?$',parsed.path))
    if not any(same_url(url) for url in bubble.get('links',[])):
        raise NeedsDecision('В меню нет проверенной ссылки выбранной вакансии')
    norm=lambda value:re.sub(r'\s+',' ',value).strip().casefold()
    sections=list(re.finditer(r'(?:^|\n)\s*(\d+)[.)]\s+(.*?)(?=\n\s*\d+[.)]\s|$)',bubble.get('text',''),re.S))
    matching=[section for section in sections if norm(identity['menu_summary']) in norm(section.group(2))]
    if len(matching)!=1:
        raise NeedsDecision('Описание вакансии отсутствует или неоднозначно; выбор остановлен')
    number=matching[0].group(1)
    expected_title=re.sub(r'^\s*\d+[.)]\s*','',identity['button_label']).strip()
    matches=[label for label in buttons if re.match(r'^\s*'+re.escape(number)+r'[.)]\s*',label)
             and norm(re.sub(r'^\s*\d+[.)]\s*','',label))==norm(expected_title)]
    if len(matches)!=1:raise NeedsDecision('Не найдена единственная кнопка проверенной вакансии')
    return matches[0]
