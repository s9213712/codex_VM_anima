"""Download the owner-selected public Anima Turbo LoRA; no credentials or paid API."""
from pathlib import Path
import hashlib,httpx
root=Path(__file__).resolve().parents[1]
path=root/'.cache/lora/anima-turbo-lora-v0.2.safetensors'
expected='1b55e40bdb1d0e5a78cb498f245fccfdaae97823265db957d2aabdcf4cd3caf1'
if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==expected:
    print('Verified Turbo v0.2 already present');raise SystemExit(0)
path.parent.mkdir(parents=True,exist_ok=True)
part=path.with_suffix('.partial')
with httpx.Client(timeout=60,follow_redirects=True) as client:
    with client.stream('GET','https://civitai.com/api/download/models/2979642?fileId=2859181') as response:
        response.raise_for_status();size=0
        with part.open('wb') as f:
            for data in response.iter_bytes():
                size+=len(data)
                if size>160*1024*1024:raise RuntimeError('Unexpected LoRA size')
                f.write(data)
if hashlib.sha256(part.read_bytes()).hexdigest()!=expected:raise RuntimeError('LoRA integrity verification failed; existing file preserved')
part.replace(path)
print('Verified Anima Turbo v0.2 SHA256; downloaded public weights, no paid API')
