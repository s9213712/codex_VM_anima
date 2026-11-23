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
