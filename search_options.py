"""Validate explicit HH search fields without network or account access."""
SEARCH_FIELDS=('name','description','company_name')
def resolve_search_fields(value=None, *, body_too=False):
    if value is None:return ['name','description'] if body_too else ['name']
    if not isinstance(value,list) or not value or any(not isinstance(v,str) or v not in SEARCH_FIELDS for v in value):
        raise ValueError('Выбери хотя бы одно поле поиска: название вакансии, описание или название компании')
    return list(dict.fromkeys(value))
