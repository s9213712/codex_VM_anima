import uuid
import pytest
from fastapi.testclient import TestClient
from anima_api import store,app as module

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'STATE',tmp_path);monkeypatch.setattr(store,'OUTPUT',tmp_path/'images');monkeypatch.setattr(store,'DB',tmp_path/'jobs.sqlite3')
    key=tmp_path/'api.key';key.write_text('unit-test-only-'+'x'*32);key.chmod(0o600)
    monkeypatch.setattr(module,'KEY',key);monkeypatch.setenv('ANIMA_TEST_NO_WORKER','1')
    with TestClient(module.app) as c:yield c

def auth():return {'Authorization':'Bearer unit-test-only-'+'x'*32}

def test_auth_and_not_ready(client):
    assert client.post('/v1/generations',json={'prompt':'lake'}).status_code==401
    assert client.post('/v1/generations',headers=auth(),json={'prompt':'lake'}).status_code==503
    assert client.get('/v1/jobs/'+str(uuid.uuid4())).status_code==401

def test_bounds(client):
    store.status('model',{'state':'READY'})
    for data in [{'prompt':'x','steps':21},{'prompt':'x','width':1024},{'prompt':'x','height':257},{'prompt':''},{'prompt':'x','seed':-1}]:
        assert client.post('/v1/generations',headers=auth(),json=data).status_code==422

def test_persistent_queue_and_backpressure(client):
    store.status('model',{'state':'READY'});ids=[]
    for i in range(2):
        r=client.post('/v1/generations',headers=auth(),json={'prompt':'test lake','steps':1});assert r.status_code==202;ids.append(r.json()['id'])
    assert client.post('/v1/generations',headers=auth(),json={'prompt':'third'}).status_code==429
    row=store.claim();assert row['id']==ids[0]
    assert client.get('/v1/jobs/'+ids[0],headers=auth()).json()['status']=='RUNNING'
    assert client.get('/v1/jobs/'+ids[0]+'/image',headers=auth()).status_code==409
    store.finish(ids[0],error='test fixture failure')
    assert client.get('/v1/jobs/'+ids[0],headers=auth()).json()['status']=='FAILED'

def test_unknown_job(client):
    assert client.get('/v1/jobs/'+str(uuid.uuid4()),headers=auth()).status_code==404

def test_restart_and_model_observation(client):
    store.status('model',{'state':'READY','model':'fixture-metadata-only'})
    store.observe_model(1024)
    assert store.status('model')['state']=='READY'
    assert store.status('model')['current_rss_bytes']==1024
    ident=store.enqueue({'prompt':'fixture'});store.claim();store.interrupted('test restart')
    assert store.get(ident)['status']=='FAILED'

def test_relay_idempotency_survives_repeated_delivery(client):
    store.status('model',{'state':'READY'})
    ident=str(uuid.uuid4());headers={**auth(),'Idempotency-Key':ident}
    a=client.post('/v1/generations',headers=headers,json={'prompt':'first'})
    b=client.post('/v1/generations',headers=headers,json={'prompt':'first'})
    assert a.status_code==202 and b.status_code==202 and a.json()['id']==b.json()['id']
    with store.connect() as c:assert c.execute('SELECT count(*) FROM jobs').fetchone()[0]==1
