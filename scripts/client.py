import argparse,json,time
from pathlib import Path
import httpx
p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8765');p.add_argument('--key-file',type=Path,default=Path('.state/api.key'))
p.add_argument('--prompt',default='masterpiece, best quality, anime scenery, a red cabin beside a calm mountain lake, sunrise, no people')
p.add_argument('--steps',type=int,default=8);p.add_argument('--size',type=int,default=256);p.add_argument('--seed',type=int,default=42)
p.add_argument('--output',type=Path,default=Path('generated.png'));p.add_argument('--evidence',type=Path)
a=p.parse_args();key=a.key_file.read_text().strip();started=time.monotonic()
local=a.url.startswith(('http://127.0.0.1:','http://localhost:'))
with httpx.Client(base_url=a.url,headers={'Authorization':'Bearer '+key},timeout=30,trust_env=not local) as c:
    r=c.post('/v1/generations',json={'prompt':a.prompt,'steps':a.steps,'width':a.size,'height':a.size,'seed':a.seed});r.raise_for_status();job=r.json()
    deadline=time.monotonic()+650
    while time.monotonic()<deadline:
        r=c.get(job['status_url']);r.raise_for_status();state=r.json();print('STATUS',state['status'],round(time.monotonic()-started,1),flush=True)
        if state['status']=='FAILED':raise RuntimeError(state['error'])
        if state['status']=='SUCCEEDED':
            r=c.get(state['image_url']);r.raise_for_status();a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_bytes(r.content)
            result={'image':str(a.output),'job':state,'http_image_status':r.status_code,'elapsed_seconds':time.monotonic()-started}
            if a.evidence:a.evidence.write_text(json.dumps(result,indent=2))
            print(json.dumps(result,indent=2));break
        time.sleep(5)
    else:raise TimeoutError('Client polling deadline exceeded')
