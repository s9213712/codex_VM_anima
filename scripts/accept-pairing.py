"""Decrypt an explicitly supplied pairing envelope locally; never print plaintext."""
import argparse,base64,hashlib,json,subprocess
from pathlib import Path
from urllib.parse import urlparse
root=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--file',type=Path,required=True);a=p.parse_args()
if a.file.stat().st_size>8192:raise SystemExit('Pairing envelope too large')
data=json.loads(a.file.read_text(encoding='utf-8'))
if data.get('version')!=1 or data.get('algorithm')!='RSA-OAEP-SHA256':raise SystemExit('Unsupported pairing format')
private=root/'.state/pairing-private.pem'
public=subprocess.run(['openssl','pkey','-in',str(private),'-pubout'],check=True,capture_output=True).stdout
if hashlib.sha256(public).hexdigest()!=data.get('public_key_sha256'):raise SystemExit('Wrong VM pairing key')
blob=base64.b64decode(data['ciphertext'],validate=True)
if len(blob)!=384:raise SystemExit('Invalid encrypted payload size')
result=subprocess.run(['openssl','pkeyutl','-decrypt','-inkey',str(private),'-pkeyopt','rsa_padding_mode:oaep','-pkeyopt','rsa_oaep_md:sha256'],input=blob,capture_output=True)
if result.returncode:raise SystemExit('Pairing decryption failed')
payload=json.loads(result.stdout);u=urlparse(payload.get('url',''));key=payload.get('agent_key','')
if u.scheme!='https' or not u.hostname or not u.hostname.endswith('.workers.dev') or u.path not in ('','/') or u.username or u.password or u.query or u.fragment:raise SystemExit('Unexpected relay URL')
if not isinstance(key,str) or not 32<=len(key)<=128:raise SystemExit('Invalid application key')
for name,value in [('relay-agent.key',key),('relay-public-url.txt',payload['url'].rstrip('/'))]:
    file=root/'.state'/name;file.write_text(value);file.chmod(0o600)
print('Pairing credential saved locally. Start the agent and verify actual authenticated connectivity; decryption alone is not a connection test.')
