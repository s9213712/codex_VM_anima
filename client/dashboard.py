#!/usr/bin/env python3
"""Personal localhost browser client for the private GitHub Anima image inbox."""
import argparse,json,os,secrets,shutil,subprocess,sys,tempfile,threading,time,urllib.parse,uuid,webbrowser
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
try:
    from .history import History
    from .anima_client import API,ClientError,params
    from .github_transport import GitHub,GitHubError,issue_id
except ImportError:
    from history import History
    from anima_client import API,ClientError,params
    from github_transport import GitHub,GitHubError,issue_id

class LocalServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,client,config,history_root=None):
        super().__init__(address,Handler);self.client=client;self.config=config;self.nonce=secrets.token_urlsafe(32)
        namespace=config.get('api') or config.get('repo','unconfigured')
        self.history=History(history_root or Path(__file__).with_name('history-data'),namespace)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def origin(self):return 'http://127.0.0.1:'+str(self.server.server_port)
    def check_host(self):return self.headers.get('Host') in ('127.0.0.1:'+str(self.server.server_port),'localhost:'+str(self.server.server_port))
    def send_data(self,data,status=200,mime='application/json; charset=utf-8'):
        if not isinstance(data,bytes):data=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def authorized(self):
        if not self.check_host():self.send_data({'error':'Invalid local Host'},403);return False
        if not secrets.compare_digest(self.headers.get('X-Local-Session',''),self.server.nonce):self.send_data({'error':'Local session required'},403);return False
        origin=self.headers.get('Origin')
        if origin and origin not in (self.origin(),'http://localhost:'+str(self.server.server_port)):self.send_data({'error':'Cross-origin requests not allowed'},403);return False
        return True
    def do_GET(self):
        if not self.check_host():self.send_data({'error':'Invalid local Host'},403);return
        path=urllib.parse.urlparse(self.path).path
        if path=='/':
            page=Path(__file__).with_name('dashboard.html').read_text(encoding='utf-8').replace('__LOCAL_NONCE__',self.server.nonce)
            self.send_data(page.encode(),mime='text/html; charset=utf-8');return
        if not self.authorized():return
        try:
            if path=='/api/resources':self.send_data(self.server.client.resources());return
            if path=='/api/history':
                warning=None;remote_ids=set();remote_rows=[]
                try:
                    if not hasattr(self.server.client,'history'):raise ClientError('Remote history is not supported by this backend')
                    data=self.server.client.history()
                    remote_rows=data.get('jobs',[])
                    for state in remote_rows:
                        if self.server.history.remember(state) is False:warning='Local history reached its 1000-record limit; new cloud jobs are visible but not archived'
                        remote_ids.add(str(state['id']))
                except (ClientError,GitHubError,OSError,ValueError) as error:warning=str(error)
                merged={str(row['id']):row for row in self.server.history.list()}
                merged.update({str(row['id']):row for row in remote_rows})
                def timestamp(row):
                    value=row.get('created') or row.get('started') or 0
                    return value/1000 if value>1e12 else value
                rows=sorted(merged.values(),key=timestamp,reverse=True)[:200]
                for row in rows:
                    row['local_snapshot']=str(row['id']) not in remote_ids
                    row['preview_cached']=self.server.history.has_image(row['id'])
                self.send_data({'jobs':rows,'warning':warning,'remote_retention_seconds':86400,'local_image_limit_bytes':100*1024*1024});return
            if path=='/api/config':
                self.send_data({'backend':self.server.config.get('backend'),'repo':self.server.config.get('repo'),
                  'cloud_start_configured':bool(self.server.config.get('codex_environment_id')),'vm_create_supported':False});return
            if path.startswith('/api/jobs/'):
                pieces=path.removeprefix('/api/jobs/').split('/');ident=pieces[0]
                if len(pieces)==1:
                    try:
                        state=self.server.client.status(ident);self.server.history.remember(state)
                    except (ClientError,GitHubError,OSError) as error:
                        state=self.server.history.get(ident)
                        if not state:raise
                        state={**state,'local_snapshot':True,'history_warning':str(error)}
                    self.send_data(state);return
                if len(pieces)==2 and pieces[1]=='image':
                    data=self.server.history.image(ident)
                    if data is None:
                        data=self.server.client.download(ident)
                        state=self.server.history.get(ident) or {}
                        self.server.history.save_image(ident,data,(state.get('metadata') or {}).get('sha256'))
                    self.send_data(data,mime='image/png');return
            self.send_data({'error':'Not found'},404)
        except (ClientError,GitHubError,OSError,ValueError) as e:self.send_data({'error':str(e)},502)
    def do_POST(self):
        if not self.authorized():return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=12000:raise ClientError('Invalid request size')
            data=json.loads(self.rfile.read(length))
            if self.path=='/api/submit':
                request=params(data.get('prompt'),negative_prompt=data.get('negative_prompt','low quality, blurry'),size=int(data.get('size',256)),width=int(data.get('width',data.get('size',256))),height=int(data.get('height',data.get('size',256))),steps=int(data.get('steps',8)),seed=int(data.get('seed',42)))
                state=self.server.client.submit(request);self.server.history.remember({**state,'request':request});self.send_data(state,202);return
            if self.path=='/api/cloud-task':
                env=self.server.config.get('codex_environment_id','')
                if not env:raise ClientError('No published Codex Cloud environment configured; this is not a VM wake API')
                if not shutil.which('codex') and not shutil.which('codex.exe'):raise ClientError('Install official Codex CLI and use codex login on this computer')
                repo=self.server.config['repo'];branch=self.server.config.get('source_branch','work/anima-restore')
                task='Run the approved Anima image inbox in this repository. Do not enable paid resources, merge main, or read secret file contents. Use the provided credentials normally. Run scripts/install.sh, start scripts/start.sh in a bounded terminal, then run .venv/bin/python github_queue/worker.py --repo '+repo+' --seconds 2400. Stay within the provider task lifetime and report actual failures. Do not claim a VM was created before work starts.'
                with tempfile.TemporaryDirectory() as temporary:
                    file=Path(temporary)/'task.txt';file.write_text(task,encoding='utf-8')
                    result=subprocess.run([sys.executable,str(Path(__file__).with_name('cloud_task.py')),'submit-task','--env',env,'--branch',branch,'--task-file',str(file)],capture_output=True,text=True,timeout=120)
                if result.returncode:raise ClientError('Cloud task not submitted; verify the environment and native ChatGPT CLI login using cloud_task.py probe')
                self.send_data({'status':'CLOUD_TASK_SUBMITTED','output':result.stdout[:3000],'note':'Task acceptance does not prove this VM is awake'});return
            self.send_data({'error':'Not found'},404)
        except (ClientError,GitHubError,OSError,ValueError,subprocess.TimeoutExpired) as e:self.send_data({'error':str(e)},400)

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,default=Path(__file__).with_name('connection.json'));p.add_argument('--port',type=int,default=0);p.add_argument('--no-browser',action='store_true');p.add_argument('--seconds',type=int,default=0);a=p.parse_args()
    if a.seconds!=0 and not 10<=a.seconds<=10800:p.error('Optional client lifetime must be 10..10800; 0 is unlimited')
    if not a.config.exists():raise SystemExit('Connection configuration missing; use the supplied client package')
    config=json.loads(a.config.read_text(encoding='utf-8'));client=GitHub(config['repo']) if config.get('backend')=='github' else API(config['api'],Path(config['key_file']).read_text(encoding='utf-8').strip())
    server=LocalServer(('127.0.0.1',a.port),client,config);url='http://127.0.0.1:'+str(server.server_port)
    print('Anima local client:',url,flush=True)
    timer=threading.Timer(a.seconds,server.shutdown);timer.daemon=True
    if a.seconds:timer.start()
    if not a.no_browser:webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:timer.cancel();server.server_close()
if __name__=='__main__':main()
