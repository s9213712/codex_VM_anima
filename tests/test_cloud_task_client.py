import subprocess,sys
import pytest
from client import cloud_task

def test_api_key_login_is_not_used_for_cloud_task_requests(monkeypatch):
    calls=[]
    def simulated(args,timeout=45):
        calls.append(args)
        if args==['--version']:return subprocess.CompletedProcess(args,0,'codex test fixture','')
        if args==['cloud','exec','--help']:return subprocess.CompletedProcess(args,0,'Usage --env ENV','')
        if args==['login','status']:return subprocess.CompletedProcess(args,0,'Logged in using an API key (ChatGPT-compatible test fixture)','')
        raise AssertionError('Cloud API must not be called for API-key login in zero-extra-API-budget mode')
    monkeypatch.setattr(cloud_task,'call',simulated)
    proof=cloud_task.probe()
    assert proof['login_reports_chatgpt'] is False
    assert proof['cloud_access_verified'] is False
    assert not any(x[:2]==['cloud','list'] for x in calls)

def test_unverified_auth_never_submits_a_task(monkeypatch,tmp_path):
    monkeypatch.setattr(cloud_task,'probe',lambda env:{'task_dispatch_command_present':True,'cloud_access_verified':False})
    monkeypatch.setattr(cloud_task,'call',lambda *a,**k:pytest.fail('No task request may be sent'))
    task=tmp_path/'task.txt';task.write_text('fixture task')
    monkeypatch.setattr(sys,'argv',['cloud_task.py','submit-task','--env','example-env','--task-file',str(task)])
    with pytest.raises(SystemExit) as e:cloud_task.main()
    assert e.value.code==2
