import hashlib,json,os,shutil,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('HF_HOME',str(ROOT/'.cache/huggingface'))
os.environ.setdefault('HF_HUB_DISABLE_XET','1')
os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT','120')
from huggingface_hub import snapshot_download
repo='circlestone-labs/Anima-Base-v1.0-Diffusers';revision='073c3a9db359c31ad0e8aa268d15775473c2176c'
if shutil.disk_usage(ROOT).free<8*1024**3 and not (ROOT/'.state/model-path.txt').exists():raise RuntimeError('Need 8GiB disk headroom')
p=Path(snapshot_download(repo,revision=revision,max_workers=2,allow_patterns=['*.json','*.safetensors','*.jinja','*.md'],cache_dir=ROOT/'.cache/huggingface/hub'))
infofile=ROOT/'.state/model-info.json'
if not infofile.exists():infofile=ROOT/'docs/evidence/model-info.json'
info=json.loads(infofile.read_text());verified=[]
for f in info['siblings']:
    if 'lfs' not in f:continue
    file=p/f['rfilename'];digest=hashlib.sha256()
    with file.open('rb') as stream:
        while block:=stream.read(8*1024*1024):digest.update(block)
    if digest.hexdigest()!=f['lfs']['sha256']:raise RuntimeError('Checksum mismatch: '+f['rfilename'])
    verified.append({'file':f['rfilename'],'bytes':file.stat().st_size,'sha256':digest.hexdigest()})
(ROOT/'.state/model-path.txt').write_text(str(p))
(ROOT/'.state/weight-integrity.json').write_text(json.dumps({'revision':revision,'completed_at':time.time(),'files':verified},indent=2))
print('VERIFIED_MODEL',p,flush=True)
