"""Synchronize the offline installer payload with reviewed project sources."""
from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parents[1];payload=root/'updater/payload'
for name in ('dashboard.py','dashboard.html','anima_client.py','github_transport.py','cloud_task.py','history.py'):
    (payload/'client'/name).write_bytes((root/'client'/name).read_bytes())
(payload/'relay/src/worker.js').write_bytes((root/'relay/src/worker.js').read_bytes())
(root/'windows-relay/src/worker.js').write_bytes((root/'relay/src/worker.js').read_bytes())
for name in ('package.json','package-lock.json'):(payload/'relay'/name).write_bytes((root/'relay'/name).read_bytes())
version=json.loads((payload/'client/installed-version.json').read_text())['version']
files={p.relative_to(payload).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(payload.rglob('*')) if p.is_file()}
(root/'updater/manifest.json').write_text(json.dumps({'version':version,'files':files},indent=2)+'\n')
print('Updater payload synchronized:',version)
