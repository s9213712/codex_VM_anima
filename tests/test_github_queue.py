import copy,json,time,uuid
import pytest
from client.github_transport import GitHubError,parse_issue,validate
from github_queue.worker import Worker,LostLease,BudgetReached

def issue(data=None):
    request=data or {'version':1,'request_id':str(uuid.uuid4()),'prompt':'a lake','steps':8}
    return {'number':12,'html_url':'https://github.com/example/private/issues/12','body':'<!-- anima-job-v1 -->\n```json\n'+json.dumps(request)+'\n```','author_association':'OWNER'}

def test_only_fixed_image_fields_and_no_credentials():
    assert parse_issue(issue())[1]['steps']==8
    for extra in [{'url':'http://internal/'},{'command':'id'},{'steps':99},{'width':257},{'prompt':'ghp_'+'A'*36}]:
        data={'version':1,'request_id':str(uuid.uuid4()),'prompt':'x',**extra}
        with pytest.raises(GitHubError):validate(data)

def test_mobile_issue_form_is_parsed_without_executing_content():
    row={'number':5,'html_url':'https://github.com/example/private/issues/5','body':'### Prompt\n\nred cabin\n\n### Negative prompt\n\n_No response_\n\n### Size\n\n256\n\n### Steps\n\n8\n\n### Seed\n\n42'}
    ident,data=parse_issue(row);assert uuid.UUID(ident) and data['width']==256 and data['seed']==42
    row['body']+='\n### Prompt\n\nsecond'
    with pytest.raises(GitHubError):parse_issue(row)

class Storage:
    def __init__(self):self.rows={};self.versions={}
    def read(self,path):return copy.deepcopy(self.rows.get(path)),self.versions.get(path)
    def write(self,path,data,sha=None,message=''):
        if self.versions.get(path)!=sha:raise GitHubError('CAS conflict',409)
        self.rows[path]=copy.deepcopy(data);self.versions[path]=str(uuid.uuid4());return {'content':{'sha':self.versions[path]}}

def test_remote_lock_fences_second_vm_and_old_owner():
    store=Storage();first=Worker('example/private');second=Worker('example/private');first.github=store;second.github=store
    assert first.lock() and not second.lock()
    store.rows['worker-lock.json']['lease_until']=0
    assert second.lock()
    with pytest.raises(LostLease):first.live()
    first.unlock();assert store.rows['worker-lock.json']['owner']==second.owner

def test_daily_budget_is_persistent_and_bounded():
    store=Storage();worker=Worker('example/private');worker.github=store
    for i in range(20):worker.budget()
    with pytest.raises(BudgetReached):worker.budget()

def test_untrusted_issue_never_reaches_local_generator():
    class Backend(Storage):
        def profile(self):return {'private':True}
        def api(self,*args):return [{**issue(),'author_association':'NONE'}]
    class Local:
        def post(self,*args,**kwargs):pytest.fail('Untrusted issue reached image executor')
    worker=Worker('example/private');worker.github=Backend()
    assert worker.run_one(Local(),time.monotonic()+10)['state']=='IDLE'
