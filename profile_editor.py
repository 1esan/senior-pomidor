import io,json,re,zipfile,datetime
from pathlib import Path
from common import BASE
from runtime import save_json,operation_lock
FIELDS={'name','city','phone','telegram','salary_min','salary_max','military_id','work_formats','office_cities','employment_types','mobility','business_travel','extra_notes','resume_text','profile_confirmed','job_search_reason','screening_answers','screening_guidance','work_format_priority','hybrid_office_days_max','hybrid_office_days_preferred'}
def extract_text(filename,data):
    if not data or len(data)>10*1024*1024:raise ValueError('Файл должен быть от 1 байта до 10 МБ')
    ext=Path(filename).suffix.lower()
    if ext=='.pdf':
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(data))
        if len(reader.pages)>100:raise ValueError('Не больше 100 страниц')
        text='\n'.join(p.extract_text() or '' for p in reader.pages)
    elif ext=='.docx':
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(i.file_size for i in z.infolist())>30*1024*1024:raise ValueError('Слишком большой распакованный DOCX')
        from docx import Document
        d=Document(io.BytesIO(data));text='\n'.join([p.text for p in d.paragraphs]+[' | '.join(c.text for c in row.cells) for t in d.tables for row in t.rows])
    elif ext in ('.txt','.md'):text=data.decode('utf-8-sig')
    else:raise ValueError('Поддерживаются PDF, DOCX, TXT, MD')
    if len(text.strip())<30:raise ValueError('Текста почти нет; для скана нужен распознанный текст')
    if len(text)>100000:raise ValueError('Не больше 100 тысяч символов')
    return text.strip()

def update_profile(old,changes):
    if not isinstance(changes,dict) or set(changes)-FIELDS:raise ValueError('Неизвестные поля профиля')
    p={**old,**changes}
    for k in ["office_cities","employment_types","mobility"]:
        if isinstance(p.get(k),str):p[k]=[v.strip() for v in p[k].split(",") if v.strip()]
    for k in ['name','city','phone','telegram','extra_notes','resume_text','job_search_reason','screening_answers','screening_guidance','hybrid_office_days_preferred']:
        if not isinstance(p.get(k,''),str):raise ValueError('Текстовое поле: '+k)
        if len(p.get(k,''))>(100000 if k=='resume_text' else 15000 if k in ('screening_answers','screening_guidance') else 5000):raise ValueError('Слишком длинное поле: '+k)
    if not p.get('name','').strip() or len(p.get('resume_text','').strip())<30:raise ValueError('Нужны имя и текст резюме')
    for k in ['salary_min','salary_max']:
        if isinstance(p[k],bool):raise ValueError('Зарплата должна быть числом')
        p[k]=int(p[k])
        if not 1<=p[k]<=10000000:raise ValueError('Некорректная зарплата')
    if p['salary_min']>p['salary_max']:raise ValueError('Минимум больше максимума')
    for k in ['work_formats','office_cities','employment_types','mobility']:
        if not isinstance(p.get(k,[]),list) or any(not isinstance(v,str) or len(v)>200 for v in p.get(k,[])):raise ValueError('Ожидается список: '+k)
    if not set(p.get('work_formats',[]))<= {'Удалёнка','Гибрид','Офис'}:raise ValueError('Неизвестный формат')
    for k in ['military_id','business_travel']:
        if p.get(k) is not None and type(p[k]) is not bool:raise ValueError('Да/нет/неизвестно: '+k)
    priority=p.get('work_format_priority',[])
    if not isinstance(priority,list) or len(priority)!=len(set(priority)) or not set(priority)<=set(p.get('work_formats',[])):raise ValueError('Некорректный приоритет форматов')
    days=p.get('hybrid_office_days_max')
    if days is not None and (type(days) is not int or not 0<=days<=5):raise ValueError('Офисных дней в гибриде: 0–5')
    if p.get('profile_confirmed') is not True:raise ValueError('Подтвердите достоверность профиля')
    if 'resume_text' in changes and changes['resume_text']!=old.get('resume_text'):p['resume_source']='Обновлено пользователем в панели'
    p['updated_at']=datetime.datetime.now().isoformat()
    return p

def save_profile(changes):
    # Prevent an operation from using a profile that changes halfway through a send.
    with operation_lock('hh'),operation_lock('telegram'),operation_lock('profile'):
        path=BASE/'giga_profile.json';old=json.loads(path.read_text());p=update_profile(old,changes)
        stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        save_json(BASE/'.state/profile-history'/(stamp+'.json'),old)
        save_json(path,p)
    return p
