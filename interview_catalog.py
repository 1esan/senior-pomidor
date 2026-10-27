"""Own HH invitations and deterministic Telegram vacancy identity matching."""
import collections,hashlib,html,json,re,time
from pathlib import Path
from urllib.parse import urlsplit,urljoin
from html.parser import HTMLParser
import requests
from runtime import save_json
from employer_guard import ensure_contact,ContactBlocked
from autonomous_runtime import NeedsDecision,invitation_links


def normalize(text):
    return ' '.join(re.findall(r'[\w]+',html.unescape(text or '').casefold().replace('ё','е')))


def plain(text):
    return html.unescape(re.sub('<[^>]+>',' ',text or ''))


def numbered_entries(bubble):
    text=bubble.get('text','');buttons=bubble.get('buttons',[]);result=[]
    for match in re.finditer(r'(?:^|\n)\s*(\d+)[.)]\s+(.*?)(?=\n\s*\d+[.)]\s|$)',text,re.S):
        num=match[1];section=match[2].split('Вы всегда можете сменить вакансию')[0].strip()
        labels=[b for b in buttons if re.match(r'^\s*'+re.escape(num)+r'[.)]\s',b)]
        if len(labels)!=1:continue
        title=re.sub(r'^\s*\d+[.)]\s*','',labels[0]).strip()
        links=bubble.get('section_links',{}).get(num,[])
        # No global link-to-row guessing: equal titles can have different URLs.
        result.append({'number':num,'label':labels[0],'title':title,'text':section,'links':links})
    return result


def official_id(url):
    try:
        p=urlsplit(url)
        if p.scheme!='https' or p.hostname!='rabota.sber.ru' or p.port not in (None,443) or p.username is not None or p.password is not None:return None
    except (ValueError,TypeError):return None
    match=re.fullmatch(r'/search/(?:[a-zA-Z0-9_-]*-)?(\d+)/?',p.path)
    return match[1] if match else None


def public_vacancy_key(url):
    oid=official_id(url)
    if oid:return 'sber:'+oid
    try:
        p=urlsplit(url)
        if p.scheme!='https' or p.hostname not in ('rabota.ru','www.rabota.ru') or p.port not in (None,443) or p.username is not None or p.password is not None:return None
        match=re.fullmatch(r'/vacancy/(\d+)/?',p.path)
        return 'rabota:'+match[1] if match else None
    except (ValueError,TypeError):return None


class TextHTML(HTMLParser):
    def __init__(self):super().__init__();self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript'):self.hidden+=1
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript'):self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)


PUBLIC_CACHE={}

def public_text(url):
    oid=public_vacancy_key(url)
    if not oid:raise ValueError('Непроверенная ссылка вакансии')
    cached=PUBLIC_CACHE.get(url)
    if cached and time.time()-cached[0]<900:return cached[1]
    session=requests.Session();session.trust_env=False
    current=url;visited=set();deadline=time.monotonic()+25
    try:
        # Sber uses /id -> /id/ -> /slug-id/. Follow only this same vacancy.
        for _ in range(5):
            if current in visited or public_vacancy_key(current)!=oid:return ''
            visited.add(current)
            remaining=deadline-time.monotonic()
            if remaining<=0:return ''
            response=session.get(current,timeout=(min(5,remaining),min(10,remaining)),allow_redirects=False,stream=True)
            try:
                if response.status_code in (301,302,303,307,308):
                    location=response.headers.get('Location')
                    if not location:return ''
                    current=urljoin(current,location)
                    if public_vacancy_key(current)!=oid:return ''
                    continue
                if response.status_code!=200:return ''
                chunks=[];size=0
                for chunk in response.iter_content(65536):
                    size+=len(chunk)
                    if size>2_000_000 or time.monotonic()>deadline:return ''
                    chunks.append(chunk)
                parser=TextHTML();parser.feed(b''.join(chunks).decode('utf-8',errors='replace'))
                text=' '.join(parser.parts).strip()
                body=b''.join(chunks).decode('utf-8',errors='replace')
                def descriptions(value):
                    if isinstance(value,dict):
                        kind=value.get('@type');kinds=kind if isinstance(kind,list) else [kind]
                        if 'JobPosting' in kinds and isinstance(value.get('description'),str):yield plain(value['description'])
                        for child in value.values():yield from descriptions(child)
                    elif isinstance(value,list):
                        for child in value:yield from descriptions(child)
                for payload in re.findall(r'<script[^>]*type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>',body,re.I|re.S):
                    try:text+=' '+' '.join(descriptions(json.loads(payload)))
                    except (ValueError,TypeError,RecursionError):pass
                # Do not cache empty/transient responses for the entire run.
                if text:
                    if len(PUBLIC_CACHE)>=128:PUBLIC_CACHE.pop(next(iter(PUBLIC_CACHE)))
                    PUBLIC_CACHE[url]=(time.time(),text)
                return text
            finally:response.close()
        return ''
    finally:session.close()


def description_signature(item):
    return hashlib.sha256(normalize(item.get('description','')).encode()).hexdigest()


def learned_candidates(base,candidates):
    try:learned=json.loads((base/'.state/giga-menu-links.json').read_text())
    except (OSError,ValueError):learned={}
    if not isinstance(learned,dict):learned={}
    result=[]
    for original in candidates:
        item={**original,'official_ids':list(original.get('official_ids',[]))}
        for oid,record in learned.items():
            if not isinstance(record,dict):continue
            if (record.get('vacancy_id')==item['id'] and record.get('employer_id')==item.get('employer_id')
                and record.get('description_hash')==description_signature(item)
                and official_id(record.get('official_url',''))==oid):
                if oid not in item['official_ids']:item['official_ids'].append(oid)
        result.append(item)
    return result


def remember_link(base,entry,item,proof):
    if proof!='official_description':return
    urls=list(dict.fromkeys(url for url in entry.get('links',[]) if official_id(url)))
    # Persist only one unambiguous row-scoped official card, tied to this HH text.
    if len(urls)!=1:return
    path=base/'.state/giga-menu-links.json'
    try:learned=json.loads(path.read_text())
    except (OSError,ValueError):learned={}
    if not isinstance(learned,dict):learned={}
    oid=official_id(urls[0])
    learned[oid]={'official_url':urls[0],'vacancy_id':item['id'],'employer_id':item['employer_id'],
        'description_hash':description_signature(item),'verified_at':time.time(),'proof':proof}
    save_json(path,learned)


def description_match(text,candidates):
    """Require several unique verbatim description fragments, never a model guess."""
    words=normalize(text).split();haystack=' '+' '.join(words)+' '
    sets={c['id']:set(tuple(normalize(c.get('description','')).split()[i:i+8]) for i in range(max(0,len(normalize(c.get('description','')).split())-7))) for c in candidates}
    counts=collections.Counter(shingle for shingles in sets.values() for shingle in shingles)
    matches=[]
    for c in candidates:
        source=normalize(c.get('description','')).split();covered=set();fragments=0
        for i in range(max(0,len(source)-7)):
            shingle=tuple(source[i:i+8])
            if counts[shingle]==1 and ' '+' '.join(shingle)+' ' in haystack:
                covered.update(range(i,i+8));fragments+=1
        if len(covered)>=24 and fragments>=6:matches.append(c)
    return matches[0] if len(matches)==1 else None


def summary_match(text,candidates):
    """Require a unique four-word anchor plus a separate corroborating fragment."""
    words=normalize(text).split()
    if len(words)<9:return None
    catalog={c['id']:normalize(c.get('description','')).split() for c in candidates}
    grams={vid:set(tuple(tokens[i:i+3]) for i in range(max(0,len(tokens)-2))) for vid,tokens in catalog.items()}
    owners=collections.Counter(g for gs in grams.values() for g in gs)
    result=[]
    for candidate in candidates:
        covered=set();unique=set();hits=[]
        for i in range(len(words)-2):
            gram=tuple(words[i:i+3])
            if gram in grams[candidate['id']]:
                hits.append(i);covered.update(range(i,i+3))
                if owners[gram]==1:unique.update(range(i,i+3))
        # A title or one common fragment cannot decide an interview identity.
        spans=[]
        for position in sorted(covered):
            if not spans or position>spans[-1][-1]+1:spans.append([position])
            else:spans[-1].append(position)
        unique_anchor=any(all(position in unique for position in range(i,i+4)) for i in range(max(0,len(words)-3)))
        if unique_anchor and len(covered)>=8 and len(hits)>=4 and len(spans)>=2 and all(len(span)>=3 for span in spans):result.append(candidate)
    return result[0] if len(result)==1 else None


def entry_key(entry):
    # Position and numbering may change. Content and each row's own URLs may not.
    urls=sorted(set(public_vacancy_key(url) or url for url in entry.get('links',[])))
    value=[normalize(entry.get('title','')),normalize(entry.get('text','')),urls]
    return hashlib.sha256(json.dumps(value,ensure_ascii=False).encode()).hexdigest()


def remember_entry(base,entry,item,proof):
    if proof not in ('summary_unique_description','official_description','official_id','audited_public_description'):return
    path=base/'.state/giga-entry-identities.json'
    try:records=json.loads(path.read_text())
    except (OSError,ValueError):records={}
    if not isinstance(records,dict):records={}
    records[entry_key(entry)]={'vacancy_id':item['id'],'employer_id':item['employer_id'],'negotiation_id':item.get('negotiation_id'),
        'description_hash':description_signature(item),'verified_at':time.time(),'proof':proof,'urls':entry.get('links',[])}
    save_json(path,records)


def known_entry(base,entry,candidates):
    try:records=json.loads((base/'.state/giga-entry-identities.json').read_text())
    except (OSError,ValueError):return None
    record=records.get(entry_key(entry)) if isinstance(records,dict) else None
    if not isinstance(record,dict):return None
    matches=[c for c in candidates if c['id']==record.get('vacancy_id') and c['employer_id']==record.get('employer_id')
        and c.get('negotiation_id')==record.get('negotiation_id') and description_signature(c)==record.get('description_hash')]
    if len(matches)!=1:return None
    if record.get('proof')=='summary_unique_description':
        current=summary_match(entry.get('text',''),candidates)
        if not current or current['id']!=matches[0]['id']:return None
    if record.get('proof') not in ('summary_unique_description','official_description','official_id','audited_public_description'):return None
    return matches[0]


def match_entry(entry,candidates,fetch=public_text,allow_unique_title=True):
    # Every candidate was obtained from this account's employer invitation.
    same=[c for c in candidates if normalize(c['name'])==normalize(entry['title'])]
    for url in entry.get('links',[]):
        oid=official_id(url)
        linked=[candidate for candidate in candidates if oid and oid in candidate.get('official_ids',[])]
        if len(linked)==1:return linked[0],'official_id'
    if len(same)==1 and allow_unique_title:return same[0],'unique_invited_title'
    pool=(same or candidates) if allow_unique_title else candidates
    summary=summary_match(entry.get('text',''),candidates)
    if summary and (not same or summary in same):return summary,'summary_unique_description'
    for url in entry.get('links',[]):
        oid=official_id(url)
        if not public_vacancy_key(url):continue
        linked=[c for c in pool if oid in c.get('official_ids',[])]
        if len(linked)==1:return linked[0],'official_id'
        text=fetch(url)
        if text:
            match=description_match(text,pool)
            if match:return match,'official_description'
    return None,'ambiguous_or_unmatched'


def discover(base,read,*,ttl=300,max_pages=50,employer_ids=('3529',),force=False,progress=None):
    path=base/'.state/giga-catalog.json';now=time.time()
    try:cached=json.loads(path.read_text())
    except (FileNotFoundError,ValueError):cached={}
    intents_path=base/'.state/hh/application-intents.json'
    signature=hashlib.sha256(intents_path.read_bytes()).hexdigest() if intents_path.exists() else ''
    if not force and cached.get('complete',False) and now-cached.get('refreshed_at',0)<ttl and signature==cached.get('applications_signature'):
        return cached
    if progress:progress('Собираю очередь из откликов и приглашений HH')
    previous={v['id']:v for v in cached.get('items',[])};items={};issues=[];negotiations={}
    for group in ('active','archived'):
        for page in range(max_pages):
            response=read(f'/negotiations?page={page}&per_page=100&status={group}')
            for negotiation in response.get('items',[]):
                v=negotiation.get('vacancy') or {};employer=v.get('employer') or {}
                if str(employer.get('id')) in employer_ids and str(v.get('id','')).isdigit():negotiations[str(v['id'])]=negotiation
            if page+1>=response.get('pages',1):break
        else:raise NeedsDecision('Не удалось полностью прочитать отклики; очередь не объявляется завершённой')
    for index,(vid,n) in enumerate(negotiations.items(),1):
        if progress and (index==1 or index%5==0):progress(f"Проверяю приглашения HH: {index}/{len(negotiations)}")
        v=n['vacancy'];nid=str(n['id']);old=previous.get(vid)
        try:
            ensure_contact(v)
            if old and old.get('negotiation_id')==nid and now-old.get('verified_at',0)<max(ttl,3600):
                items[vid]=old;continue
            links=set()
            for page in range(max_pages):
                messages=read(f'/negotiations/{nid}/messages?page={page}&per_page=100')
                links.update(invitation_links(messages.get('items',[])))
                if page+1>=messages.get('pages',1):break
            else:raise NeedsDecision('Переписка приглашения не прочитана полностью')
            if not links:continue
            full=read('/vacancies/'+vid);ensure_contact(full)
            if str(full.get('id'))!=vid or str(full['employer']['id'])!=str(v['employer']['id']):raise NeedsDecision('Изменилась принадлежность вакансии')
            description=plain(full.get('description',''));oids=set()
            for url in re.findall(r'https?://[^\s<>"\']+',html.unescape(full.get('description',''))):
                oid=official_id(url)
                if oid:oids.add(oid)
            identity_path=base/'.state/giga-menu-identities'/(vid+'.json')
            if identity_path.exists():
                identity=json.loads(identity_path.read_text())
                if identity.get('employer_id')==str(full['employer']['id']) and normalize(identity.get('hh_identity_phrase','')) in normalize(description):oids.add(identity['official_id'])
            items[vid]={'id':vid,'name':full['name'],'company':full['employer']['name'],'employer_id':str(full['employer']['id']),'negotiation_id':nid,'description':description,'official_ids':sorted(oids),'verified_at':now}
        except ContactBlocked as exc:issues.append({'vacancy_id':vid,'blocked':True,'reason':str(exc)})
        except (requests.RequestException,NeedsDecision) as exc:issues.append({'vacancy_id':vid,'blocked':False,'reason':str(exc)})
    result={'version':1,'refreshed_at':now,'applications_signature':signature,'items':list(items.values()),'issues':issues,'complete':not any(not i.get('blocked') for i in issues)}
    save_json(path,result);return result


def select_entry(base,bubble,state,catalog,preferred=None,fetch=public_text,strategy="first",required_id=None):
    candidates=learned_candidates(base,catalog['items']);rows=numbered_entries(bubble);choices=[];unresolved={};pending=[]
    completed=state.get('completed_interviews',{})
    binding_path=base/'.state/telegram-bindings.json'
    bindings={normalize(k):v for k,v in json.loads(binding_path.read_text()).items()} if binding_path.exists() else {}
    title_counts=collections.Counter(normalize(row['title']) for row in rows)
    def resolve(row,fetcher):
        known=known_entry(base,row,candidates)
        if known:return known,'verified_entry_identity'
        item,proof=match_entry(row,candidates,fetcher,allow_unique_title=title_counts[normalize(row['title'])]==1)
        manual=bindings.get(normalize(row['title']))
        if manual and title_counts[normalize(row['title'])]==1:
            bound=[candidate for candidate in candidates if candidate['id']==str(manual.get('vacancy_id')) and candidate['employer_id']==str(manual.get('employer_id'))]
            if len(bound)==1:
                if item and item['id']!=bound[0]['id']:return None,'manual_binding_conflicts_with_identity'
                item=bound[0];proof='user_confirmed_binding'
        if item:
            remember_link(base,row,item,proof)
            remember_entry(base,row,item,proof)
        return item,proof
    def consider(row,item,proof):
        if item:
            if 'hh:'+item['id'] in completed:
                if completed['hh:'+item['id']].get('legacy_identity_unverified'):
                    unresolved[row['label']]={'label':row['label'],'vacancy_id':item['id'],'reason':'legacy_completion_needs_review'}
                return
            choices.append((item,row,proof))
        else:unresolved[row['label']]={'label':row['label'],'reason':proof}
    def unique_choices():
        counts=collections.Counter(c['id'] for c,_,_ in choices)
        for candidate,row,_ in choices:
            if counts[candidate['id']]>1:unresolved[row['label']]={'label':row['label'],'reason':'duplicate_identity'}
        return [entry for entry in choices if counts[entry[0]['id']]==1 and (required_id is None or str(entry[0]['id'])==str(required_id))]
    # Resolve available exact identities first; a slow public page must never
    # delay already verified unique titles on this menu page.
    for row in rows:
        item,proof=resolve(row,lambda url:'')
        consider(row,item,proof)
        if item is None and proof!='manual_binding_conflicts_with_identity':pending.append(row)
    unique=unique_choices()
    if not unique:
        for row in pending:
            try:item,proof=resolve(row,fetch)
            except requests.RequestException:
                item,proof=None,'official_page_unavailable'
            if item:unresolved.pop(row['label'],None)
            consider(row,item,proof)
        unique=unique_choices()
    if required_id is not None:unique=[entry for entry in unique if str(entry[0]['id'])==str(required_id)]
    if strategy=='senior':unique.sort(key=lambda entry:not bool(re.search(r'senior|ведущ|старш|lead',entry[0]['name'],re.I)))
    if preferred:unique.sort(key=lambda entry:entry[0]['id']!=preferred['id'])
    if not unique:return None,None,list(unresolved.values())
    item,row,proof=unique[0];scope=dict(item)
    scope['selection']={'selected_at':time.time(),'menu_fingerprint':__import__('telegram_state').fingerprint(bubble),'label':row['label'],'proof':proof,'title':row['title'],'section':row['text']}
    return scope,row['label'],list(unresolved.values())


def intro_identity(text):
    match=re.search(r'получил[аи]?\s+(?:ваш\s+)?отклик\s+на\s+позицию\s+([^\n]+)',text,re.I)
    if match:return match[1].strip().rstrip('. ')
    # Giga may resume with just the title and the last question, without its intro.
    match=re.search(r'(?:давайте\s+)?продолжим\s+общение\s+по\s+вакансии\s+([^\n]+?)(?=\.?\s*мы\s+остановились|\r?\n|$)',text,re.I)
    return match[1].strip().rstrip('. ') if match else None


def scope_from_intro(text,catalog,current=None,allow_selected=False):
    title=intro_identity(text)
    if not title:return None
    candidates=catalog['items'];same=[c for c in candidates if normalize(c['name'])==normalize(title)]
    # The caller permits this only for a confirmed click or the exact previously
    # verified intro. HH ID, employer and application define the interview;
    # the recruiter's display title is not an identity key.
    if allow_selected and current and current.get('selection'):
        selected=[c for c in candidates if c['id']==current['id']
                  and c.get('employer_id')==current.get('employer_id')
                  and c.get('negotiation_id')==current.get('negotiation_id')]
        if len(selected)!=1:
            raise NeedsDecision('Подтверждённый ID вакансии или отклик изменился; контекст сохранён')
        return {**current,**selected[0],'selection':current['selection']}
    # Without a confirmed selection the intro still needs independent evidence.
    match=description_match(text,same or candidates)
    if match:return dict(match)
    if len(same)==1:return dict(same[0])
    raise NeedsDecision('Текущее интервью не удалось однозначно сопоставить с откликом HH; старая память не используется')
