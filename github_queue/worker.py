"""Single-worker, fenced private-GitHub image inbox. No Actions or arbitrary commands."""
import argparse,base64,datetime,hashlib,io,json,sys,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from PIL import Image
from client.github_transport import GitHub,GitHubError,BRANCH,LABEL,parse_issue
from anima_api.settings import ROOT,KEY,STATE

class LostLease(RuntimeError):pass
class BudgetReached(RuntimeError):pass

class Worker:
    def __init__(self,repo):self.github=GitHub(repo);self.owner=str(uuid.uuid4());self.current=None
    def put(self,path,data,sha=None,message='Update image job state'):return self.github.write(path,data,sha,message)
    def lock(self):
        row,sha=self.github.read('worker-lock.json')
        if row and row.get('lease_until',0)>time.time() and row.get('owner')!=self.owner:return False
        try:self.put('worker-lock.json',{'owner':self.owner,'lease_until':time.time()+900},sha)
        except GitHubError as e:
            if e.status in (409,422):return False
            raise
        return True
    def live(self):
        row,_=self.github.read('worker-lock.json')
        if not row or row.get('owner')!=self.owner or row.get('lease_until',0)<=time.time():raise LostLease('Remote worker lease lost; no result will be published')
    def unlock(self):
        row,sha=self.github.read('worker-lock.json')
        if row and row.get('owner')==self.owner:self.put('worker-lock.json',{'owner':None,'lease_until':0},sha)
    def heartbeat(self,local):
        response=local.get('/v1/system');response.raise_for_status();data=response.json();data.update(observed_at=time.time(),worker_id=self.owner)
        _,sha=self.github.read('system.json')
        self.put('system.json',data,sha,'VM resource snapshot')
    def state(self,number,**changes):
        path='jobs/'+str(number)+'.json';old,sha=self.github.read(path);data=old or {'id':str(number),'created':time.time()}
        if old and old.get('status')=='RUNNING' and old.get('lease_owner') not in (None,self.owner):raise LostLease('Job is owned by another worker')
        data.update(changes);self.put(path,data,sha);return data
    def budget(self):
        data,sha=self.github.read('budget.json');data=data or {'days':{},'uploaded_bytes':0}
        day=datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        if data['days'].get(day,0)>=20 or data.get('uploaded_bytes',0)+2*1024*1024>100*1024*1024:raise BudgetReached('Application budget reached (20 tasks/UTC day or 100MiB stored images)')
        data['days'][day]=data['days'].get(day,0)+1
        data['days']=dict(sorted(data['days'].items())[-7:]);self.put('budget.json',data,sha)
    def add_bytes(self,count):
        data,sha=self.github.read('budget.json');data['uploaded_bytes']=data.get('uploaded_bytes',0)+count;self.put('budget.json',data,sha)
    def run_one(self,local,deadline):
        self.github.profile()
        issues=self.github.api('GET','/issues?state=open&labels='+LABEL+'&sort=created&direction=asc&per_page=50')
        selected=None
        for issue in issues:
            if 'pull_request' in issue or issue.get('author_association') not in ('OWNER','MEMBER','COLLABORATOR'):continue
            row,_=self.github.read('jobs/'+str(issue['number'])+'.json')
            if row and row.get('status') in ('SUCCEEDED','FAILED','BLOCKED'):continue
            selected=issue;break
        if not selected:return {'state':'IDLE'}
        if not self.lock():return {'state':'BUSY'}
        number=selected['number'];self.current=number
        try:
            row,_=self.github.read('jobs/'+str(number)+'.json')
            if row and row.get('status')=='RUNNING':
                # Interrupted expensive work requires review; never silently regenerate it on another VM.
                if row.get('lease_until',0)>time.time():return {'state':'BUSY'}
                # Fenced takeover for reporting failure after the old global lease expired.
                row['lease_owner']=self.owner;_,sha=self.github.read('jobs/'+str(number)+'.json');self.put('jobs/'+str(number)+'.json',row,sha)
                self.state(number,status='FAILED',error='Prior VM interrupted; inspect any saved result and explicitly resubmit',finished=time.time());return {'state':'FAILED','id':str(number)}
            _,request=parse_issue(selected);self.budget()
            self.state(number,status='RUNNING',request=request,started=time.time(),lease_owner=self.owner,lease_until=time.time()+900,error=None)
            operation=str(uuid.uuid5(uuid.NAMESPACE_URL,'https://github.com/'+self.github.repo+'/issues/'+str(number)))
            response=local.post('/v1/generations',headers={'Idempotency-Key':operation},json=request);response.raise_for_status();local_id=str(uuid.UUID(response.json()['id']))
            self.state(number,local_id=local_id,checkpoint='LOCAL_SUBMITTED')
            end=min(deadline,time.monotonic()+650);last_check=0
            while time.monotonic()<end:
                response=local.get('/v1/jobs/'+local_id);response.raise_for_status();job=response.json()
                if job['status']=='FAILED':raise RuntimeError(job.get('error') or 'Local generation failed')
                if job['status']=='SUCCEEDED':break
                if time.monotonic()-last_check>60:self.live();self.heartbeat(local);last_check=time.monotonic()
                time.sleep(5)
            else:raise TimeoutError('Image generation deadline exceeded')
            self.live()
            response=local.get('/v1/jobs/'+local_id+'/image');response.raise_for_status();png=response.content
            if len(png)>2*1024*1024:raise RuntimeError('Image exceeds 2MiB transport limit')
            Image.open(io.BytesIO(png)).verify();digest=hashlib.sha256(png).hexdigest()
            if digest!=job['metadata']['sha256']:raise RuntimeError('Image checksum mismatch')
            saved=STATE/'github-results'/(str(number)+'.png');saved.parent.mkdir(exist_ok=True);saved.write_bytes(png);saved.chmod(0o600)
            self.state(number,checkpoint='GENERATED',metadata=job['metadata'])
            self.live()
            path='results/'+str(number)+'.png'
            # Avoid overwriting a previously published image. New issue numbers have new paths.
            try:existing=self.github.api('GET','/contents/'+path+'?ref='+BRANCH)
            except GitHubError as e:
                if e.status!=404:raise
                existing=None
            if existing:raise RuntimeError('Result path already exists; review it before retrying')
            result=self.github.api('PUT','/contents/'+path,{'message':'Image result #'+str(number),'branch':BRANCH,'content':base64.b64encode(png).decode()})
            self.add_bytes(len(png))
            url='https://github.com/'+self.github.repo+'/blob/'+BRANCH+'/'+path
            self.state(number,status='SUCCEEDED',finished=time.time(),metadata=job['metadata'],result_url=url,commit_sha=result['commit']['sha'],checkpoint='PUBLISHED',lease_until=0)
            body=(selected.get('body') or '')+'\n\nResult: [generated PNG]('+url+')\n\nSHA256: `'+digest+'`'
            self.github.api('PATCH','/issues/'+str(number),{'state':'closed','body':body})
            self.heartbeat(local);return {'state':'SUCCEEDED','id':str(number),'result_url':url}
        except LostLease:raise
        except Exception as error:
            try:self.state(number,status='BLOCKED' if isinstance(error,BudgetReached) else 'FAILED',error=type(error).__name__+': '+str(error)[:1500],finished=time.time(),lease_until=0)
            except (GitHubError,LostLease):pass
            return {'state':'FAILED','id':str(number),'error':type(error).__name__}
        finally:
            self.current=None
            try:self.unlock()
            except GitHubError:pass

def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--seconds',type=int,default=10800);p.add_argument('--once',action='store_true');a=p.parse_args()
    if not 10<=a.seconds<=10800:p.error('Worker lifetime must be 10..10800 seconds')
    worker=Worker(a.repo);deadline=time.monotonic()+a.seconds;heartbeat=0
    with httpx.Client(base_url='http://127.0.0.1:8765',headers={'Authorization':'Bearer '+KEY.read_text().strip()},timeout=20,trust_env=False) as local:
        while time.monotonic()<deadline:
            try:
                if time.monotonic()-heartbeat>120:worker.heartbeat(local);heartbeat=time.monotonic()
                result=worker.run_one(local,deadline);print(json.dumps(result),flush=True)
                if a.once:return
                if result['state'] in ('IDLE','BUSY'):time.sleep(30)
            except (GitHubError,LostLease,httpx.HTTPError) as e:
                print('WORKER_PAUSED',type(e).__name__,flush=True)
                if a.once:raise SystemExit(2)
                time.sleep(60)
if __name__=='__main__':main()
