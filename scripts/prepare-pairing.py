"""Create a VM-specific public-key pairing ZIP; never export its private key."""
import argparse,hashlib,subprocess,zipfile
from pathlib import Path
from urllib.parse import urlparse
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--url',required=True);a=p.parse_args()
u=urlparse(a.url)
if u.scheme!='https' or not u.hostname or not u.hostname.endswith('.workers.dev') or u.path not in ('','/') or u.query or u.fragment or u.username or u.password:raise SystemExit('Expected an HTTPS workers.dev origin')
state=root/'.state';state.mkdir(exist_ok=True);state.chmod(0o700);private=state/'pairing-private.pem'
if not private.exists():
    subprocess.run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:3072','-out',str(private)],check=True,capture_output=True);private.chmod(0o600)
bundle=state/'pairing-package/vm-pairing';bundle.mkdir(parents=True,exist_ok=True)
subprocess.run(['openssl','pkey','-in',str(private),'-pubout','-out',str(bundle/'vm-public.pem')],check=True,capture_output=True)
source=(root/'pairing/pair-vm.cjs').read_text()
source=source.replace('https://anima.s92137123.workers.dev',a.url.rstrip('/'))
(bundle/'pair-vm.cjs').write_text(source)
(bundle/'Pair-VM.ps1').write_bytes((root/'pairing/Pair-VM.ps1').read_bytes())
output=state/'vm-pairing.zip'
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
    for file in bundle.iterdir():z.write(file,'vm-pairing/'+file.name)
print('Download only this public-key tool:',output)
print('Public-key fingerprint:',hashlib.sha256((bundle/'vm-public.pem').read_bytes()).hexdigest())
