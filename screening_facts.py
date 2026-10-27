"""Deterministic answers only for explicitly confirmed profile facts."""
import re,json

def known_answer(question,options,opened,profile):
    facts=profile.get('screening_answers','')
    q=question.casefold().replace('ё','е')
    text=None;positive=False
    if 'средн' in q and 'балл' in q and re.search(r'диплом|бакалавр|специалитет|образован',q):
        m=re.search(r'Средний балл диплома бакалавра:\s*(\d(?:[.,]\d+)?)',facts,re.I)
        if m:text='Средний балл диплома бакалавра: '+m[1].replace(',','.')+'.'
    elif re.search(r'выступали ли|есть ли[^?]{0,50}выступ|приходилось ли[^?]{0,50}выступ',q) and re.search(r'Публичные выступления:\s*выступал перед аудиторией более 10 человек',facts,re.I):
        text='Да, выступал перед аудиторией более 10 человек.';positive=True
    elif ('последн' in q and re.search(r'двух|2',q) and re.search(r'трудоустро|оформл',q)
          and re.search(r'Оформление на последних двух местах работы:\s*официально по ТК РФ в штате',facts,re.I)):
        text='Да, на последних двух местах работы был официально трудоустроен по ТК РФ в штате.';positive=True
    elif re.search(r'опыт|стаж',q) and re.search(r'сколько|длительн|количеств',q) and re.search(r'лет|год',q):
        m=re.search(r'(?:^|\n)Стаж:\s*(\d+)\s*(?:год\w*|лет)\s*(?:(\d+)\s*месяц\w*)?',facts,re.I)
        if not m:return None
        years=int(m[1]);months=int(m[2] or 0)
        text=f'{years} года {months} месяцев коммерческого опыта системным аналитиком.'
        if options and not opened:
            eligible=[]
            for oid,label in options.items():
                label=label.casefold().replace('ё','е')
                span=re.search(r'(\d+)\s*[-–—]\s*(\d+)\s*(?:год|лет)',label)
                # Year buckets refer to completed years; 4y6m is not 5+.
                if span and int(span[1])<=years<=int(span[2]):eligible.append(oid)
                elif re.search(r'менее\s+(\d+)',label):
                    if years+months/12 < int(re.search(r'менее\s+(\d+)',label)[1]):eligible.append(oid)
                elif re.search(r'(?:от|не менее)\s*(\d+)',label):
                    if years>=int(re.search(r'(?:от|не менее)\s*(\d+)',label)[1]):eligible.append(oid)
                elif re.search(r'(\d+)\s*(?:лет|год\w*)\s*(?:и более|/более|\+)',label):
                    if years>=int(re.search(r'(\d+)\s*(?:лет|год\w*)',label)[1]):eligible.append(oid)
            if len(eligible)==1:return json.dumps({'choice_ids':eligible,'text':'','needs_review':False},ensure_ascii=False)
            return None
    if text is None:return None
    if positive and options:
        yes=[oid for oid,label in options.items() if re.fullmatch(r'да[.! ]*',label.strip(),re.I)]
        if len(yes)==1:return json.dumps({'choice_ids':yes,'text':'','needs_review':False},ensure_ascii=False)
    if opened:return json.dumps({'choice_ids':[],'text':text,'needs_review':False},ensure_ascii=False)
    return None
