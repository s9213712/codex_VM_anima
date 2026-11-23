#!/usr/bin/env python3
"""Optional official Codex Cloud task dispatch; NOT a VM create/wake/stop API."""
import argparse,json,os,re,shutil,subprocess,sys
from pathlib import Path

class CloudError(RuntimeError):pass

def call(args,timeout=45):
    executable=shutil.which('codex.exe') or shutil.which('codex')
    if not executable:raise CloudError('Install the official Codex CLI on this device and sign in with codex login')
    if os.name=='nt' and Path(executable).suffix.lower() in ('.cmd','.bat'):raise CloudError('Use the official native codex.exe for this optional launcher; batch-script launchers are not accepted')
    return subprocess.run([executable,*args],capture_output=True,text=True,timeout=timeout)

def probe(env=None):
    version=call(['--version'])
    help_result=call(['cloud','exec','--help'])
    auth=call(['login','status'])
    chatgpt=auth.returncode==0 and bool(re.search(r'^Logged in using ChatGPT\s*$',auth.stdout+'\n'+auth.stderr,re.M))
    listing=call(['cloud','list','--json','--limit','1',*(['--env',env] if env else [])]) if chatgpt else None
    accessible=listing is not None and listing.returncode==0
    detail='read-only cloud task listing succeeded' if accessible else 'Cloud account access not verified; sign in on this device and recheck'
    return {'cli_version':version.stdout.strip(),'task_dispatch_command_present':help_result.returncode==0 and '--env' in help_result.stdout,
       'login_reports_chatgpt':chatgpt,'cloud_access_verified':accessible,'note':detail,
       'vm_create':False,'vm_wake':False,'same_vm_reuse_guaranteed':False,'remaining_codex_quota':None,'automatic_paid_fallback':False}

def checked_env(value):
    if value.startswith('ccarenv_'):raise CloudError('This managed computer ID is not a verified Codex Cloud task environment ID; use an environment shown in your Codex Cloud account')
    if not re.fullmatch(r'[A-Za-z0-9_-]{3,200}',value):raise CloudError('Invalid Codex Cloud environment identifier')
    return value

def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    check=s.add_parser('probe');check.add_argument('--env')
    create=s.add_parser('submit-task');create.add_argument('--env',required=True);create.add_argument('--branch');create.add_argument('--task-file',type=Path,required=True)
    status=s.add_parser('status');status.add_argument('task_id')
    a=p.parse_args()
    try:
        if a.command=='probe':print(json.dumps(probe(checked_env(a.env) if a.env else None),ensure_ascii=False,indent=2));return
        if a.command=='status':
            if not re.fullmatch(r'[A-Za-z0-9_-]{3,200}',a.task_id):raise CloudError('Invalid cloud task identifier')
            result=call(['cloud','status',a.task_id])
        else:
            env=checked_env(a.env);proof=probe(env)
            if not proof['task_dispatch_command_present'] or not proof['cloud_access_verified']:
                raise CloudError('Cloud dispatch is not authorized on this device; no cloud task was submitted')
            task=a.task_file.read_text(encoding='utf-8')
            if not task.strip() or len(task.encode())>12000:raise CloudError('Task file must contain 1..12000 UTF-8 bytes')
            if re.search(r'(gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY)',task):raise CloudError('Potential credential in task text; use the environment secret store')
            args=['cloud','exec','--env',env,'--attempts','1']
            if a.branch:
                if a.branch.startswith('-') or len(a.branch)>200:raise CloudError('Invalid source branch')
                args+=['--branch',a.branch]
            result=call([*args,task],timeout=60)
        # Cloud task quota/authentication errors stop here; there is no automatic retry or API-key fallback.
        if result.returncode:raise CloudError('Official cloud CLI rejected the request; check authentication, environment access and native quota. Nothing was retried automatically.')
        print(result.stdout.strip())
    except subprocess.TimeoutExpired:
        print('UNKNOWN: submission response timed out. Check codex cloud list/status before retrying; the task may already exist.',file=sys.stderr);raise SystemExit(2)
    except (CloudError,OSError) as e:print('ERROR:',str(e),file=sys.stderr);raise SystemExit(2)
if __name__=='__main__':main()
