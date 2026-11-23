import hashlib,io,json,time,uuid
from pathlib import Path
import httpx
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
key=(ROOT/'.state/api.key').read_text().strip()
with httpx.Client(base_url='http://127.0.0.1:8765',trust_env=False,timeout=10) as c:
    health=c.get('/healthz');health.raise_for_status()
    unauthorized=c.post('/v1/generations',json={'prompt':'lake'});assert unauthorized.status_code==401
    invalid=c.post('/v1/generations',headers={'Authorization':'Bearer '+key},json={'prompt':'lake','steps':999});assert invalid.status_code==422
    proof={'observed_at':time.time(),'health_status':health.status_code,'health':health.json(),'without_key':unauthorized.status_code,'invalid_parameters':invalid.status_code}
    record=ROOT/'docs/evidence/real-generation.json'
    if record.exists():
        result=json.loads(record.read_text());row=result['job'];r=c.get('/v1/jobs/'+row['id']+'/image',headers={'Authorization':'Bearer '+key});r.raise_for_status()
        image=Image.open(io.BytesIO(r.content));size=image.size;image.verify()
        assert hashlib.sha256(r.content).hexdigest()==row['metadata']['sha256']
        proof.update(image_status=r.status_code,image_size=list(size),image_sha256=row['metadata']['sha256'])
    (ROOT/'docs/evidence/live-api-verification.json').write_text(json.dumps(proof,indent=2))
    print(json.dumps(proof,indent=2))
