import hashlib
import pytest
from client.history import History

def test_history_survives_restart_and_scopes_endpoints(tmp_path):
    h=History(tmp_path,'https://one.example')
    h.remember({'id':'older','status':'FAILED','created':1000,'request':{'prompt':'first'}})
    h.remember({'id':'newer','status':'SUCCEEDED','created':2000000000000,'request':{'prompt':'second'}})
    h.remember({'id':'older','status':'FAILED'})
    reopened=History(tmp_path,'https://one.example')
    assert [r['id'] for r in reopened.list()]==['newer','older']
    assert reopened.get('older')['request']['prompt']=='first'
    assert History(tmp_path,'https://two.example').list()==[]

def test_cached_png_integrity_and_path_traversal(tmp_path):
    h=History(tmp_path,'endpoint');png=b'\x89PNG\r\n\x1a\nexample';sha=hashlib.sha256(png).hexdigest()
    with pytest.raises(ValueError):h.save_image('job',png,'0'*64)
    h.save_image('job',png,sha)
    assert History(tmp_path,'endpoint').image('job')==png
    with pytest.raises(ValueError):h.image('../secret')
    with pytest.raises(ValueError):h.save_image('job2',b'not a png')
