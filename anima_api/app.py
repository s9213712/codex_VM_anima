import asyncio,contextlib,json,os,secrets,subprocess,sys,time,uuid
from contextlib import asynccontextmanager
import psutil
from fastapi import Depends,FastAPI,HTTPException,Header
from fastapi.security import HTTPAuthorizationCredentials,HTTPBearer
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field,field_validator
from . import store
from .settings import ROOT,STATE,OUTPUT,KEY

bearer=HTTPBearer(auto_error=False)
def auth(credential:HTTPAuthorizationCredentials|None=Depends(bearer)):
    if not KEY.exists() or len(KEY.read_text().strip())<32:raise HTTPException(503,'API key not provisioned')
    if not credential or not secrets.compare_digest(credential.credentials,KEY.read_text().strip()):raise HTTPException(401,'Bearer API key required')

class Generate(BaseModel):
    prompt:str=Field(min_length=1,max_length=1500)
    negative_prompt:str=Field(default='low quality, blurry',max_length=1000)
    width:int=Field(default=256,ge=128,le=1024)
    height:int=Field(default=256,ge=128,le=1024)
    steps:int=Field(default=8,ge=1,le=20)
    seed:int=Field(default=42,ge=0,le=2**32-1)
    @field_validator('width','height')
    @classmethod
    def multiple32(cls,value):
        if value%32:raise ValueError('Dimensions must be multiples of 32')
        return value

async def supervise(child):
    started=time.monotonic();last_update=0
    try:
        while child.poll() is None:
            await asyncio.sleep(1)
            rss=psutil.Process(child.pid).memory_info().rss
            if rss>12*1024**3:raise RuntimeError('Worker exceeded 12GiB RSS budget')
            with store.connect() as c:row=c.execute("SELECT started FROM jobs WHERE status='RUNNING' LIMIT 1").fetchone()
            if time.monotonic()-last_update>5:
                store.observe_model(rss);last_update=time.monotonic()
        raise RuntimeError('Model worker exited: '+str(child.returncode))
    except asyncio.CancelledError:raise
    except Exception as e:store.status('model',{'state':'ERROR','error':str(e)});store.interrupted(str(e))
    finally:
        if child.poll() is None:
            child.terminate()
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:child.kill();child.wait()

@asynccontextmanager
async def lifespan(app):
    app.state.started_at=time.time()
    store.init();store.interrupted('Service restarted; resubmit explicitly')
    if os.environ.get('ANIMA_TEST_NO_WORKER')=='1':yield;return
    store.status('model',{'state':'LOADING','device':'cpu','dtype':'bfloat16'})
    log=(STATE/'worker.log').open('a')
    env={k:v for k,v in os.environ.items() if k in {'PATH','LANG','LC_ALL','SSL_CERT_FILE','SSL_CERT_DIR'}}
    env.update(OMP_NUM_THREADS='4',MKL_NUM_THREADS='4',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HOME=str(ROOT/'.cache/huggingface'))
    child=subprocess.Popen([sys.executable,'-u','-m','anima_api.worker'],cwd=ROOT,env=env,stdout=log,stderr=log)
    monitor=asyncio.create_task(supervise(child))
    try:yield
    finally:
        monitor.cancel()
        with contextlib.suppress(asyncio.CancelledError):await monitor
        log.close()

app=FastAPI(title='Anima CPU API',version='0.2.0',lifespan=lifespan)
@app.get('/healthz')
def health():
    model=store.status('model') or {'state':'STARTING'}
    return {'ready':model.get('state')=='READY','model':model,'ephemeral':True}
@app.post('/v1/generations',status_code=202,dependencies=[Depends(auth)])
def generate(request:Generate,idempotency_key:uuid.UUID|None=Header(default=None)):
    if (store.status('model') or {}).get('state')!='READY':raise HTTPException(503,'Model not ready')
    try:ident=store.enqueue(request.model_dump(),str(idempotency_key) if idempotency_key else None)
    except OverflowError as e:raise HTTPException(429,str(e),headers={'Retry-After':'30'})
    return {'id':ident,'status_url':'/v1/jobs/'+ident}
@app.get('/v1/jobs/{ident}',dependencies=[Depends(auth)])
def job(ident:uuid.UUID):
    row=store.get(str(ident))
    if not row:raise HTTPException(404,'Job not found')
    logfile=STATE/'job-logs'/(str(ident)+'.log')
    row['log_tail']=logfile.read_bytes()[-8192:].decode('utf-8',errors='replace') if logfile.exists() else ''
    row['progress']=store.status('progress:'+str(ident));row['request']=json.loads(row['request']);row['metadata']=json.loads(row['metadata']) if row['metadata'] else None
    if row['status']=='SUCCEEDED':row['image_url']='/v1/jobs/'+str(ident)+'/image'
    return row
@app.get('/v1/jobs/{ident}/image',dependencies=[Depends(auth)])
def image(ident:uuid.UUID):
    row=store.get(str(ident))
    if not row:raise HTTPException(404,'Job not found')
    if row['status']!='SUCCEEDED':raise HTTPException(409,'Image not ready')
    file=OUTPUT/(str(ident)+'.png')
    if not file.is_file():raise HTTPException(410,'Image artifact no longer available')
    return FileResponse(file,media_type='image/png',filename=str(ident)+'.png')

@app.get('/v1/system',dependencies=[Depends(auth)])
def system_resources():
    from .metrics import snapshot
    return snapshot(store.status('model') or {},app.state.started_at)
