"""Inspect only staged blobs; never print matched secrets or contact values."""
from pathlib import Path
import json,re,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def git(*args):
 return subprocess.check_output(['git',*args],cwd=ROOT)
files=[p.decode() for p in git('diff','--cached','--name-only','--diff-filter=ACMR','-z').split(b'\0') if p]
if '--all' in sys.argv:
 files=[p.decode() for p in git('ls-files','-z').split(b'\0') if p]
blocked=[]
secret=re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{25,}|sk-(?!test-)[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----')
contacts=[]
profile=ROOT/'giga_profile.json'
if profile.exists():
 try:
  data=json.loads(profile.read_text())
  for k in ('name','telegram'):
   if isinstance(data.get(k),str) and len(data[k])>=5:contacts.append(data[k])
  phone=re.sub(r'\D','',data.get('phone',''))
 except (ValueError,OSError):
  print('Cannot inspect local profile; commit blocked.');sys.exit(1)
else:phone=''
for name in files:
 p=Path(name)
 if any(x in p.parts for x in ('.state','.browsers','.venv','logs','__pycache__')) or p.name in ('giga_profile.json','statistics.json','hh-data.json','test_sources.json','personal_launcher.json') or p.suffix in ('.session','.sqlite3','.sqlite','.db','.pem','.key') or p.name.startswith('.env'):
  blocked.append((name,'private file'));continue
 raw=git('show',':'+name)
 try:text=raw.decode('utf-8')
 except UnicodeError:
  blocked.append((name,'binary file needs explicit review'));continue
 if secret.search(text):blocked.append((name,'credential pattern'))
 if any(value in text for value in contacts):blocked.append((name,'personal profile value'))
 if phone and len(phone)>=10:
  for match in re.finditer(r'(?:\+?7|8)[ \t()\-]*\d(?:[ \t()\-]*\d){9}',text):
   digits=re.sub(r'\D','',match.group())
   if digits[-10:]==phone[-10:]:blocked.append((name,'personal phone'));break
if blocked:
 for name,reason in blocked:print(f'BLOCKED: {name}: {reason}')
 sys.exit(1)
print(f'Index privacy check OK: {len(files)} files')
