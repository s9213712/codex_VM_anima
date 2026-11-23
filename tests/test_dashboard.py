import threading
import httpx
from client.dashboard import LocalServer

class Fixture:
    def resources(self):return {'online':False,'note':'test fixture'}

def test_local_ui_requires_host_and_session_and_blocks_cross_site():
    app=LocalServer(('127.0.0.1',0),Fixture(),{'backend':'github','repo':'example/private'})
    thread=threading.Thread(target=app.serve_forever,daemon=True);thread.start()
    url='http://127.0.0.1:'+str(app.server_port)
    try:
        with httpx.Client(base_url=url,trust_env=False) as c:
            assert c.get('/').status_code==200
            assert c.get('/',headers={'Host':'evil.example'}).status_code==403
            assert c.get('/api/resources').status_code==403
            h={'X-Local-Session':app.nonce}
            assert c.get('/api/resources',headers=h).json()['online'] is False
            assert c.post('/api/submit',headers={**h,'Origin':'https://evil.example'},json={'prompt':'x'}).status_code==403
            assert c.get('/api/config',headers=h).json()['vm_create_supported'] is False
    finally:app.shutdown();app.server_close()

def test_history_requires_auth_and_can_preview_cached_image_when_remote_offline(tmp_path):
    import hashlib
    class Client:
        offline=False
        def history(self):
            if self.offline:raise OSError('offline fixture')
            return {'jobs':[{'id':'test-job','status':'SUCCEEDED','created':1000,'request':{'prompt':'<script>untrusted</script>','width':768,'height':512,'steps':8},'metadata':{'sha256':hashlib.sha256(png).hexdigest()}}]}
        def download(self,ident):
            if self.offline:raise OSError('offline fixture')
            return png
    png=b'\x89PNG\r\n\x1a\nfixture';remote=Client()
    app=LocalServer(('127.0.0.1',0),remote,{'backend':'http','api':'https://test.example'},history_root=tmp_path)
    thread=threading.Thread(target=app.serve_forever,daemon=True);thread.start()
    try:
        with httpx.Client(base_url='http://127.0.0.1:'+str(app.server_port),trust_env=False) as c:
            assert c.get('/api/history').status_code==403
            h={'X-Local-Session':app.nonce}
            rows=c.get('/api/history',headers=h).json()['jobs'];assert rows[0]['id']=='test-job'
            assert c.get('/api/jobs/test-job/image',headers=h).content==png
            remote.offline=True
            result=c.get('/api/history',headers=h).json();assert result['warning'];assert result['jobs'][0]['local_snapshot']
            assert c.get('/api/jobs/test-job/image',headers=h).content==png
    finally:app.shutdown();app.server_close()
