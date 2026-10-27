"""Shared presentation for generated HTML. Does not change report data."""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parent

def sidebar(active='overview'):
    links=[('overview','◫','Обзор','/#overview'),('launch','▷','Запуск','/#launch'),('activity','☷','Переписки','/reports/activity'),('dashboard','▥','Статистика HH','/reports/dashboard'),('settings','⚙','Настройки','/#settings')]
    anchors=''.join('<a data-eg-nav="'+key+'" href="http://127.0.0.1:8768'+url+'"'+(' aria-current="page"' if key==active else '')+'><span class="eg-icon" aria-hidden="true">'+icon+'</span>'+label+'</a>' for key,icon,label,url in links)
    return '<aside class="eg-sidebar" aria-label="Основная навигация"><a class="eg-brand" href="http://127.0.0.1:8768/#overview"><span class="eg-symbol" aria-hidden="true">↗</span>Сеньор Помидор</a><nav class="eg-nav">'+anchors+'</nav><div class="eg-sidebar-foot">Личное рабочее пространство<a href="http://127.0.0.1:8766/" target="_blank" rel="noopener">Подключение ИИ ↗</a></div></aside>'

def skin_report(source, name):
    if 'id="eg-shared-theme"' in source:
        css=(ROOT/'ui_theme.css').read_text()
        source=re.sub(r'(<style id="eg-shared-theme">).*?(</style>)',lambda m:m[1]+css+m[2],source,flags=re.S)
        if '/static/ui_theme.css' not in source:source=source.replace('</style>', '</style><link rel="stylesheet" href="http://127.0.0.1:8768/static/ui_theme.css">',1)
        return source
    css=(ROOT/'ui_theme.css').read_text()
    head='<link rel="stylesheet" href="http://127.0.0.1:8768/static/ui_theme.css"><meta name="viewport" content="width=device-width,initial-scale=1"><style id="eg-shared-theme">'+css+'</style>'
    if '<body>' in source:
        return source.replace('<body>','<body class="eg-report">'+head+sidebar(name),1)
    marker='<div class="wrap">'
    if marker in source:return source.replace(marker,head+'<body class="eg-report">'+sidebar(name)+marker,1)
    raise ValueError('Report container not found')
