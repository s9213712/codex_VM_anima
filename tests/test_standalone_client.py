import http.server,threading
from pathlib import Path
import pytest
from client.anima_client import API,ClientError,save_image

def server(handler):
    obj=http.server.ThreadingHTTPServer(('127.0.0.1',0),handler)
    thread=threading.Thread(target=obj.serve_forever,daemon=True);thread.start()
    return obj

class Silent(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass

def test_api_key_is_not_forwarded_on_http_redirect():
    seen=[]
    class Target(Silent):
        def do_GET(self):
            seen.append(self.headers.get('Authorization'));self.send_response(200);self.end_headers();self.wfile.write(b'{}')
    target=server(Target)
    class Source(Silent):
        def do_GET(self):
            self.send_response(302);self.send_header('Location','http://127.0.0.1:'+str(target.server_port)+'/capture');self.end_headers()
    source=server(Source)
    try:
        client=API('http://127.0.0.1:'+str(source.server_port),'test-only-'+'x'*32,allow_local=True)
        with pytest.raises(ClientError,match='302'):client.request('/test')
        assert seen==[]
    finally:
        source.shutdown();source.server_close();target.shutdown();target.server_close()

def test_download_refuses_to_replace_existing_files(tmp_path):
    p=tmp_path/'existing.png';p.write_bytes(b'original')
    with pytest.raises(ClientError,match='already exists'):save_image(b'\x89PNG\r\n\x1a\nfixture',p)
    assert p.read_bytes()==b'original'
