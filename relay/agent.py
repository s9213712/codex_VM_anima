"""Bounded, application-specific HTTPS image-job agent. Never a generic TCP/URL/command proxy."""
import argparse,hashlib,io,json,os,sqlite3,time,uuid
from pathlib import Path
from urllib.parse import urlparse
import httpx
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'.state'

def checkpoint(remote,**fields):
    with sqlite3.connect(STATE/'relay-agent.sqlite3') as db:
        db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
        prior=db.execute('SELECT data FROM jobs WHERE id=?',(remote,)).fetchone()
        data=json.loads(prior[0]) if prior else {};data.update(fields)
        db.execute('INSERT OR REPLACE INTO jobs(id,data) VALUES(?,?)',(remote,json.dumps(data)))
        return data

def secret(name):
    file=os.environ.get(name+'_FILE')
    value=Path(file).read_text().strip() if file else os.environ.get(name,'')
    if len(value)<32:raise RuntimeError(name+' must be supplied by Environment Secrets (or a secret file), not command arguments')
    return value

def validate_url(url,allow_local=False):
    parsed=urlparse(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('Relay URL cannot contain credentials, query or fragment')
    if parsed.scheme=='https' and parsed.hostname and parsed.path in ('','/'):return url.rstrip('/')
    if allow_local and parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','localhost') and parsed.path in ('','/'):return url.rstrip('/')
    raise ValueError('Public relay requires HTTPS; localhost is available only with explicit --local-test')

def resources(local):
    try:
        r=local.get('/v1/system');r.raise_for_status();return r.json()
    except httpx.HTTPError:return None

def execute(remote,local,job,session_deadline):
    ident=str(uuid.UUID(job['id']));lease=str(uuid.UUID(job['lease']));data=checkpoint(ident,lease=lease,lease_until=job['lease_until'],request=job['request'])
    lease_headers={'X-Lease-Token':lease}
    if not data.get('local_id'):
        r=local.post('/v1/generations',headers={'Idempotency-Key':ident},json=job['request']);r.raise_for_status()
        data=checkpoint(ident,local_id=str(uuid.UUID(r.json()['id'])))
    local_id=data['local_id'];deadline=session_deadline;heartbeat=0
    while time.monotonic()<deadline:
        r=local.get('/v1/jobs/'+local_id);r.raise_for_status();state=r.json()
        if state.get('progress'):
            progress=remote.post('/agent/jobs/'+ident+'/progress',headers=lease_headers,json={**state['progress'],'elapsed_seconds':max(0,time.time()-state['started']) if state.get('started') else 0,'log_tail':state.get('log_tail','')[-8192:]})
            if progress.status_code!=404:progress.raise_for_status()
        if state['status']=='FAILED':raise RuntimeError(state['error'])
        if state['status']=='SUCCEEDED':
            r=local.get('/v1/jobs/'+local_id+'/image');r.raise_for_status()
            if len(r.content)>2*1024*1024:raise RuntimeError('Image exceeds relay size limit')
            image=Image.open(io.BytesIO(r.content));image.verify()
            if hashlib.sha256(r.content).hexdigest()!=state['metadata']['sha256']:raise RuntimeError('Local image integrity mismatch')
            path=STATE/'relay-results'/(ident+'.png');path.parent.mkdir(exist_ok=True);path.write_bytes(r.content);path.chmod(0o600)
            checkpoint(ident,image=str(path),metadata=state['metadata'],stage='GENERATED')
            headers={**lease_headers,'Content-Type':'image/png','X-Generation-Metadata':json.dumps(state['metadata'],ensure_ascii=True)}
            # Retry the same result with the same lease; the Worker rejects conflicting replay.
            for attempt in range(3):
                try:
                    response=remote.post('/agent/jobs/'+ident+'/complete',headers=headers,content=r.content);response.raise_for_status()
                    checkpoint(ident,stage='UPLOADED');print('UPLOADED',ident,flush=True);return
                except (httpx.TransportError,httpx.HTTPStatusError):
                    if attempt==2:raise
                    time.sleep(2**attempt)
        if time.monotonic()-heartbeat>15:
            ping=remote.post('/agent/heartbeat',json={'ready':True,'busy':True,'system':resources(local)});ping.raise_for_status();heartbeat=time.monotonic()
        time.sleep(5)
    raise TimeoutError('Local generation polling deadline exceeded')

def main():
    p=argparse.ArgumentParser();p.add_argument('--url',default=os.environ.get('ANIMA_RELAY_URL'));p.add_argument('--local-test',action='store_true');p.add_argument('--once',action='store_true');p.add_argument('--seconds',type=int,default=0)
    args=p.parse_args()
    if not args.url:p.error('ANIMA_RELAY_URL or --url is required')
    if args.seconds!=0 and not 10<=args.seconds<=10800:p.error('Optional session seconds must be 10..10800; 0 has no application time limit')
    url=validate_url(args.url,args.local_test);key=secret('ANIMA_RELAY_AGENT_KEY');api_key=(STATE/'api.key').read_text().strip()
    deadline=time.monotonic()+args.seconds if args.seconds else float('inf')
    # Inherited proxy/CA remains active for the public relay; localhost traffic stays inside this VM.
    with httpx.Client(base_url=url,headers={'Authorization':'Bearer '+key},timeout=30,trust_env=not args.local_test,follow_redirects=False) as remote, \
         httpx.Client(base_url='http://127.0.0.1:8765',headers={'Authorization':'Bearer '+api_key},timeout=15,trust_env=False) as local:
        # Resume this agent's still-live leases before claiming anything new.
        dbfile=STATE/'relay-agent.sqlite3'
        if dbfile.exists():
            with sqlite3.connect(dbfile) as db:pending=db.execute('SELECT id,data FROM jobs').fetchall()
            for ident,raw in pending:
                data=json.loads(raw)
                if data.get('stage')=='UPLOADED' or data.get('lease_until',0)<=time.time()*1000:continue
                try:execute(remote,local,{'id':ident,**data},deadline)
                except (httpx.HTTPError,RuntimeError,ValueError,TimeoutError):print('RECOVERY_PENDING',ident,flush=True)
        while time.monotonic()<deadline:
            job=None
            try:
                health=local.get('/healthz');health.raise_for_status();ready=health.json()['ready']
                response=remote.post('/agent/claim',json={'ready':ready,'system':resources(local)});response.raise_for_status();job=response.json().get('job')
                if job:
                    # The server supplies only the strictly validated image schema, never commands or destination URLs.
                    execute(remote,local,job,deadline)
                    if args.once:return
                else:time.sleep(10)
            except (httpx.HTTPError,RuntimeError,ValueError,TimeoutError) as error:
                # Do not print requests, authorization headers or secret values.
                print('RELAY_ERROR',type(error).__name__,getattr(getattr(error,'response',None),'status_code',''),flush=True)
                if job:
                    try:
                        remote.post('/agent/jobs/'+str(uuid.UUID(job['id']))+'/fail',headers={'X-Lease-Token':job['lease']},json={'error':'Image worker failed: '+type(error).__name__}).raise_for_status()
                    except httpx.HTTPError:pass
                if args.once:raise SystemExit(2)
                time.sleep(10)
if __name__=='__main__':main()
