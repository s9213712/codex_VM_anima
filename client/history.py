"""Local per-endpoint history; no credentials, bounded PNG cache, no automatic deletion."""
import hashlib,json,re,sqlite3,time
from pathlib import Path

class History:
    def __init__(self,root,namespace):
        self.root=Path(root)/hashlib.sha256(namespace.encode()).hexdigest()[:20]
        self.root.mkdir(parents=True,exist_ok=True)
        self.db=self.root/'history.sqlite3'
        with self.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, seen REAL NOT NULL)')
    def connect(self):return sqlite3.connect(self.db,timeout=10)
    def ident(self,value):
        value=str(value)
        if not re.fullmatch(r'[A-Za-z0-9-]{1,64}',value):raise ValueError('Invalid history ID')
        return value
    def remember(self,state):
        ident=self.ident(state['id'])
        keep={k:state[k] for k in ('id','status','request','created','started','finished','error','metadata','issue_url') if k in state}
        prior=self.get(ident) or {}
        keep={**prior,**keep}
        keep.setdefault('created',time.time())
        with self.connect() as c:
            if not c.execute('SELECT 1 FROM jobs WHERE id=?',(ident,)).fetchone() and c.execute('SELECT count(*) FROM jobs').fetchone()[0]>=1000:return False
            c.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?)',(ident,json.dumps(keep,ensure_ascii=False),time.time()))
        return True
    def get(self,ident):
        with self.connect() as c:r=c.execute('SELECT snapshot FROM jobs WHERE id=?',(self.ident(ident),)).fetchone()
        return json.loads(r[0]) if r else None
    def list(self):
        with self.connect() as c:rows=c.execute('SELECT snapshot FROM jobs LIMIT 1000').fetchall()
        def created(row):
            value=row.get('created') or row.get('started') or 0
            return value/1000 if value>1e12 else value
        return sorted([json.loads(r[0]) for r in rows],key=created,reverse=True)[:200]
    def has_image(self,ident):return (self.root/(self.ident(ident)+'.png')).is_file()
    def image(self,ident):
        path=self.root/(self.ident(ident)+'.png')
        return path.read_bytes() if path.exists() else None
    def save_image(self,ident,data,sha=None):
        if len(data)>2*1024*1024 or not data.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Invalid history PNG')
        if sha and hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Image checksum mismatch')
        path=self.root/(self.ident(ident)+'.png')
        if path.exists():return
        if sum(p.stat().st_size for p in self.root.glob('*.png'))+len(data)>100*1024*1024:return
        part=path.with_suffix('.partial');part.write_bytes(data);part.replace(path)
