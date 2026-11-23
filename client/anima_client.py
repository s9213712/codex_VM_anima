#!/usr/bin/env python3
"""Standalone local sender: Python standard library only; no ChatGPT, Torch, or Diffusers required."""
import argparse,hashlib,json,sys,time,urllib.error,urllib.parse,urllib.request,uuid
from pathlib import Path

try:
    from .github_transport import GitHub,GitHubError
except ImportError:
    from github_transport import GitHub,GitHubError

class ClientError(RuntimeError):pass
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None

def identifier(value):
    try:return str(uuid.UUID(value))
    except (ValueError,TypeError):raise ClientError('Invalid task ID')

def params(prompt,negative_prompt='low quality, blurry',size=256,steps=8,seed=42):
    if not isinstance(prompt,str) or not 1<=len(prompt)<=1500:raise ClientError('Prompt needs 1..1500 characters')
    if len(negative_prompt)>1000:raise ClientError('Negative prompt too long')
    if not isinstance(size,int) or not 128<=size<=512 or size%32:raise ClientError('Size must be 128..512 and a multiple of 32')
    if not isinstance(steps,int) or not 1<=steps<=20:raise ClientError('Steps must be 1..20')
    if not isinstance(seed,int) or not 0<=seed<=2**32-1:raise ClientError('Invalid seed')
    return {'prompt':prompt,'negative_prompt':negative_prompt,'width':size,'height':size,'steps':steps,'seed':seed}

class API:
    def __init__(self,url,key,allow_local=False):
        parsed=urllib.parse.urlparse(url)
        local=parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','localhost')
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
            raise ClientError('API URL must not contain credentials, query, fragment or a path')
        if parsed.scheme!='https' and not (allow_local and local):raise ClientError('Use HTTPS for the external API')
        if len(key)<32:raise ClientError('API key is too short')
        self.url=url.rstrip('/');self.key=key
        # The explicit loopback test stays local. External URLs retain normal proxy and TLS trust.
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()) if local else urllib.request.build_opener(NoRedirect())
    def request(self,path,data=None,binary=False,headers=None):
        body=None if data is None else json.dumps(data).encode()
        request=urllib.request.Request(self.url+path,data=body,headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json','User-Agent':'Anima-local-client/1.0',**(headers or {})})
        try:
            with self.opener.open(request,timeout=30) as response:
                content=response.read(2*1024*1024+1)
                if len(content)>2*1024*1024:raise ClientError('Response exceeds client size limit')
                return content if binary else json.loads(content)
        except urllib.error.HTTPError as e:raise ClientError('API HTTP '+str(e.code)) from None
    def submit(self,data):return self.request('/v1/generations',data)
    def resources(self):return self.request('/v1/system')
    def status(self,ident):return self.request('/v1/jobs/'+identifier(ident))
    def download(self,ident):return self.request('/v1/jobs/'+identifier(ident)+'/image',binary=True)

def save_image(data,path,expected=None):
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):raise ClientError('Server did not return a PNG')
    if expected and hashlib.sha256(data).hexdigest()!=expected:raise ClientError('Image checksum mismatch')
    target=Path(path)
    if target.exists():raise ClientError('Output already exists; choose a new filename')
    target.parent.mkdir(parents=True,exist_ok=True);temp=target.with_suffix(target.suffix+'.partial');temp.write_bytes(data);temp.replace(target)
    return target

def wait(client,ident,timeout=1200,interval=10):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        state=client.status(ident);print('STATUS',state.get('status','PENDING'),flush=True)
        if state.get('status') in ('FAILED','BLOCKED'):raise ClientError(state.get('error') or 'Task failed')
        if state.get('status')=='SUCCEEDED':return state
        time.sleep(interval)
    raise ClientError('Wait timed out; keep your task ID and query status later')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--api');p.add_argument('--repo');p.add_argument('--key-file',type=Path);p.add_argument('--local-test',action='store_true')
    sub=p.add_subparsers(dest='command',required=True)
    submit=sub.add_parser('submit');submit.add_argument('--prompt');submit.add_argument('--prompt-file',type=Path);submit.add_argument('--size',type=int,default=256);submit.add_argument('--steps',type=int,default=8);submit.add_argument('--seed',type=int,default=42);submit.add_argument('--wait',action='store_true');submit.add_argument('--output',default='result.png')
    resources=sub.add_parser('resources');resources.add_argument('--watch',type=int,default=0,help='Refresh seconds, 1..60; omit for one snapshot');resources.add_argument('--duration',type=int,default=10800,help='Maximum watch lifetime, 1..10800 seconds')
    status=sub.add_parser('status');status.add_argument('id')
    download=sub.add_parser('download');download.add_argument('id');download.add_argument('--output',required=True)
    a=p.parse_args()
    try:
        config_file=Path(__file__).with_name('connection.json');config=json.loads(config_file.read_text()) if config_file.exists() else {}
        repo=a.repo or (config.get('repo') if not a.api else None)
        if repo:client=GitHub(repo)
        elif a.api and a.key_file:client=API(a.api,a.key_file.read_text().strip(),a.local_test)
        else:raise ClientError('Configure a private repository, or provide --api and --key-file')
        if a.command=='resources':
            if not 0<=a.watch<=60:raise ClientError('--watch must be 0..60 seconds')
            if not 1<=a.duration<=10800:raise ClientError('--duration must be 1..10800 seconds')
            deadline=time.monotonic()+a.duration
            while time.monotonic()<deadline:
                print(json.dumps(client.resources(),ensure_ascii=False,indent=2),flush=True)
                if not a.watch:return
                time.sleep(a.watch)
            return
        if a.command=='status':print(json.dumps(client.status(a.id),ensure_ascii=False,indent=2));return
        if a.command=='download':
            state=client.status(a.id);print(save_image(client.download(a.id),a.output,(state.get('metadata') or {}).get('sha256')));return
        prompt=a.prompt_file.read_text(encoding='utf-8') if a.prompt_file else a.prompt
        job=client.submit(params(prompt,size=a.size,steps=a.steps,seed=a.seed));print(json.dumps(job,ensure_ascii=False))
        if a.wait:
            state=wait(client,job['id']);print(save_image(client.download(job['id']),a.output,(state.get('metadata') or {}).get('sha256')))
    except KeyboardInterrupt:return
    except (ClientError,GitHubError,OSError) as e:print('ERROR:',str(e),file=sys.stderr);raise SystemExit(2)
if __name__=='__main__':main()
