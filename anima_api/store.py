import contextlib,json,sqlite3,time,uuid
from .settings import STATE,OUTPUT,DB

@contextlib.contextmanager
def connect():
    c=sqlite3.connect(DB,timeout=10);c.row_factory=sqlite3.Row
    try:
        with c:yield c
    finally:c.close()

def init():
    STATE.mkdir(parents=True,exist_ok=True);STATE.chmod(0o700)
    OUTPUT.mkdir(parents=True,exist_ok=True);OUTPUT.chmod(0o700)
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE IF NOT EXISTS jobs(id text PRIMARY KEY,status text NOT NULL,request text NOT NULL,created real NOT NULL,started real,finished real,error text,metadata text)')
        c.execute('CREATE TABLE IF NOT EXISTS system(key text PRIMARY KEY,value text NOT NULL)')

def status(key,value=None):
    with connect() as c:
        if value is not None:c.execute('INSERT OR REPLACE INTO system(key,value) VALUES(?,?)',(key,json.dumps(value)))
        row=c.execute('SELECT value FROM system WHERE key=?',(key,)).fetchone()
        return json.loads(row['value']) if row else None

def enqueue(data):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT count(*) FROM jobs WHERE status IN ('PENDING','RUNNING')").fetchone()[0]>=2:raise OverflowError('Queue full; retry later')
        if c.execute('SELECT count(*) FROM jobs').fetchone()[0]>=20:raise OverflowError('20-task session budget reached; review before restarting')
        ident=str(uuid.uuid4());c.execute('INSERT INTO jobs(id,status,request,created) VALUES(?,?,?,?)',(ident,'PENDING',json.dumps(data),time.time()))
        return ident

def claim():
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT * FROM jobs WHERE status='PENDING' ORDER BY created LIMIT 1").fetchone()
        if row:c.execute("UPDATE jobs SET status='RUNNING',started=? WHERE id=?",(time.time(),row['id']))
        return dict(row) if row else None

def get(ident):
    with connect() as c:
        row=c.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone()
        return dict(row) if row else None

def finish(ident,error=None,metadata=None):
    with connect() as c:c.execute('UPDATE jobs SET status=?,finished=?,error=?,metadata=? WHERE id=?',('FAILED' if error else 'SUCCEEDED',time.time(),error,json.dumps(metadata or {}),ident))

def interrupted(reason):
    with connect() as c:c.execute("UPDATE jobs SET status='FAILED',finished=?,error=? WHERE status IN ('PENDING','RUNNING')",(time.time(),reason))

def observe_model(rss):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT value FROM system WHERE key='model'").fetchone()
        state=json.loads(row['value']) if row else {'state':'LOADING'}
        state.update(current_rss_bytes=rss,observed_at=time.time())
        c.execute("INSERT OR REPLACE INTO system(key,value) VALUES('model',?)",(json.dumps(state),))
