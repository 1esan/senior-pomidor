"""Select source excerpts, preserving the original wording; no model summarisation."""
import re,hashlib,json
from pathlib import Path

def select_excerpts(text,query='',budget=9000):
    if len(text)<=budget:return text
    words=set(re.findall(r'[a-zа-яё0-9]{4,}',query.casefold()))
    sections=re.split(r'(?m)(?=^#{1,4}\s)',text)
    scored=[]
    for i,section in enumerate(sections):
        if not section.strip():continue
        tokens=set(re.findall(r'[a-zа-яё0-9]{4,}',section.casefold()))
        score=len(words&tokens)
        if i==0:score+=2
        scored.append((score,i,section))
    chosen={};remaining=budget
    for score,i,section in sorted(scored,key=lambda x:(-x[0],x[1])):
        if remaining<250:break
        value=section[:min(3500,remaining)]
        if len(value)<len(section):value=value.rsplit('\n',1)[0] or value
        chosen[i]=value;remaining-=len(value)+2
    return '\n\n'.join(chosen[i] for i in sorted(chosen))

class TestCheckpoint:
    def __init__(self,base,vid,resume_id,context):
        from runtime import save_json
        self.save=save_json
        digest=hashlib.sha256((str(resume_id)+'\n'+context).encode()).hexdigest()[:24]
        self.path=Path(base)/'.state/test-checkpoints'/f'{vid}-{digest}.json'
        try:self.data=json.loads(self.path.read_text())
        except (OSError,ValueError):self.data={}
    def key(self,task):return hashlib.sha256(json.dumps(task,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    def get(self,task):return self.data.get(self.key(task))
    def put(self,task,raw):self.data[self.key(task)]=raw;self.save(self.path,self.data)
