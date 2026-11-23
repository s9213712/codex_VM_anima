"""Private GitHub image task inbox; standard library + official GitHub CLI, no Actions."""
import base64,hashlib,json,os,re,shutil,subprocess,time,urllib.parse,uuid
from pathlib import Path
BRANCH='anima-jobs'
LABEL='anima-job'
MARKER='anima-job-v1'
class GitHubError(RuntimeError):
    def __init__(self,message,status=None):super().__init__(message);self.status=status

def issue_id(value):
    value=str(value)
    if not re.fullmatch(r'[1-9][0-9]{0,9}',value):raise GitHubError('Invalid issue task ID')
    return value

def validate(data):
    if not isinstance(data,dict):raise GitHubError('Expected image job JSON')
    allowed={'version','request_id','prompt','negative_prompt','width','height','steps','seed'}
    if set(data)-allowed:raise GitHubError('Unknown task fields')
    if data.get('version')!=1:raise GitHubError('Unsupported task version')
    try:uuid.UUID(data['request_id'])
    except (KeyError,ValueError,TypeError):raise GitHubError('Invalid request UUID')
    for key,maximum,default in [('prompt',1500,None),('negative_prompt',1000,'low quality, blurry')]:
        value=data.get(key,default)
        if not isinstance(value,str) or len(value)>maximum or (key=='prompt' and not value.strip()):raise GitHubError('Invalid '+key)
        if re.search(r'(gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{24,}|-----BEGIN [A-Z ]*PRIVATE KEY)',value):raise GitHubError('Potential credential in prompt; do not put secrets in image tasks')
    for key in ('width','height'):
        value=data.get(key,256)
        if type(value) is not int or not 128<=value<=1024 or value%32:raise GitHubError('Invalid image size')
    if type(data.get('steps',8)) is not int or not 1<=data.get('steps',8)<=20:raise GitHubError('Invalid steps')
    if type(data.get('seed',42)) is not int or not 0<=data.get('seed',42)<=4294967295:raise GitHubError('Invalid seed')
    return {'prompt':data['prompt'],'negative_prompt':data.get('negative_prompt','low quality, blurry'),
      'width':data.get('width',256),'height':data.get('height',256),'steps':data.get('steps',8),'seed':data.get('seed',42)}

def parse_issue(issue):
    if 'pull_request' in issue:raise GitHubError('Pull request is not an image task')
    body=issue.get('body') or ''
    if body.startswith('<!-- '+MARKER+' -->'):
        match=re.search(r'```json\s*\n(.*?)\n```',body,re.S)
        if not match:raise GitHubError('Task JSON block missing')
        try:data=json.loads(match.group(1))
        except json.JSONDecodeError:raise GitHubError('Invalid image task JSON')
    else:
        # GitHub Issue Form for phone/web users. Headings cannot become code or commands.
        names={'Prompt','Negative prompt','Size','Steps','Seed'};fields={}
        matches=list(re.finditer(r'^### (.+)\s*$',body,re.M))
        for i,m in enumerate(matches):
            key=m.group(1).strip()
            if key not in names or key in fields:raise GitHubError('Unexpected or duplicate form field')
            fields[key]=body[m.end():matches[i+1].start() if i+1<len(matches) else len(body)].strip()
        if 'Prompt' not in fields:raise GitHubError('Image task form missing Prompt')
        try:
            size=int(fields.get('Size','256'));steps=int(fields.get('Steps','8'));seed=int(fields.get('Seed','42'))
        except ValueError:raise GitHubError('Invalid numeric form field')
        negative=fields.get('Negative prompt','low quality, blurry')
        if negative=='_No response_':negative='low quality, blurry'
        stable=uuid.uuid5(uuid.NAMESPACE_URL,issue.get('html_url') or 'github-issue:'+str(issue['number']))
        data={'version':1,'request_id':str(stable),'prompt':fields['Prompt'],'negative_prompt':negative,'width':size,'height':size,'steps':steps,'seed':seed}
    request=validate(data)
    return data['request_id'],request

class GitHub:
    def __init__(self,repo):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise GitHubError('Use owner/repository')
        self.repo=repo
    def api(self,method,path,data=None,raw=False):
        exe=shutil.which('gh')
        if not exe:raise GitHubError('Install the official GitHub CLI, then run gh auth login')
        if os.name=='nt' and Path(exe).suffix.lower() in ('.cmd','.bat'):raise GitHubError('Use the official native gh.exe')
        if path and not path.startswith('/'):raise GitHubError('Invalid API path')
        accept='application/vnd.github.raw+json' if raw else 'application/vnd.github+json'
        args=[exe,'api','--hostname','github.com','--method',method,'-H','Accept: '+accept,'-H','Cache-Control: no-cache','repos/'+self.repo+path]
        if data is not None:args+=['--input','-']
        try:p=subprocess.run(args,input=None if data is None else json.dumps(data,ensure_ascii=False).encode(),capture_output=True,timeout=40)
        except subprocess.TimeoutExpired:raise GitHubError('Request outcome unknown; check the task before resubmitting')
        if p.returncode:
            error=p.stderr.decode(errors='replace');code=re.search(r'HTTP (\d{3})',error)
            raise GitHubError('GitHub request failed'+(' (HTTP '+code.group(1)+')' if code else '; check gh auth login/network'),int(code.group(1)) if code else None)
        if raw:return p.stdout
        return json.loads(p.stdout) if p.stdout.strip() else None
    def profile(self):
        repo=self.api('GET','')
        if repo.get('private') is not True:raise GitHubError('This client requires a private repository')
        return repo
    def read(self,path):
        try:result=self.api('GET','/contents/'+urllib.parse.quote(path,safe='/')+'?ref='+BRANCH)
        except GitHubError as e:
            if e.status==404:return None,None
            raise
        return json.loads(base64.b64decode(result['content'])),result['sha']
    def write(self,path,value,sha=None,message='Update image job state'):
        payload={'message':message,'branch':BRANCH,'content':base64.b64encode(json.dumps(value,ensure_ascii=False).encode()).decode()}
        if sha:payload['sha']=sha
        return self.api('PUT','/contents/'+urllib.parse.quote(path,safe='/'),payload)
    def submit(self,data):
        self.profile();request={'version':1,'request_id':str(uuid.uuid4()),**data};validate(request)
        body='<!-- '+MARKER+' -->\n```json\n'+json.dumps(request,ensure_ascii=False,indent=2)+'\n```'
        issue=self.api('POST','/issues',{'title':'Image: '+data['prompt'].replace('\n',' ')[:90],'body':body,'labels':[LABEL]})
        return {'id':str(issue['number']),'request_id':request['request_id'],'status':'PENDING','issue_url':issue['html_url']}
    def status(self,ident):
        ident=issue_id(ident);state,_=self.read('jobs/'+ident+'.json')
        if state:return {k:v for k,v in state.items() if k not in ('lease_owner','lease_until')}
        issue=self.api('GET','/issues/'+ident);_,request=parse_issue(issue)
        return {'id':ident,'status':'PENDING','request':request,'issue_url':issue['html_url'],'note':'Waiting for a running VM worker'}
    def download(self,ident):
        ident=issue_id(ident);state=self.status(ident)
        if state.get('status')!='SUCCEEDED':raise GitHubError('Image is not ready')
        data=self.api('GET','/contents/results/'+ident+'.png?ref='+BRANCH,raw=True)
        if len(data)>2*1024*1024 or not data.startswith(b'\x89PNG\r\n\x1a\n'):raise GitHubError('Invalid image result')
        if hashlib.sha256(data).hexdigest()!=state['metadata']['sha256']:raise GitHubError('Image checksum mismatch')
        return data
    def resources(self):
        state,_=self.read('system.json')
        if not state:return {'online':False,'note':'No VM heartbeat yet','capabilities':{'vm_create':False,'vm_wake':False}}
        age=max(0,time.time()-state['observed_at'])
        return {**state,'snapshot_age_seconds':round(age,1),'online':age<180,'capabilities':{'vm_create':False,'vm_wake':False}}
