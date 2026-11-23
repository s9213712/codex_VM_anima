import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {Miniflare} from 'miniflare';
const CLIENT='test-client-key-'+ 'c'.repeat(32),AGENT='test-agent-key-'+ 'a'.repeat(32);
const code=await readFile(new URL('../src/worker.js',import.meta.url),'utf8');
const png=await readFile(new URL('../../docs/generated-example.png',import.meta.url));
async function harness(fn){
 const mf=new Miniflare({modules:true,script:code,compatibilityDate:'2026-07-30',bindings:{CLIENT_KEY:CLIENT,AGENT_KEY:AGENT},durableObjects:{RELAY:{className:'AnimaRelay',useSQLite:true}}});
 const req=(path,{key=CLIENT,method='GET',body,headers={}}={})=>mf.dispatchFetch('https://relay.test'+path,{method,headers:{Authorization:'Bearer '+key,...headers},body});
 try{await fn(req);}finally{await mf.dispose();}
}
const submit=(req,data={prompt:'test lake'})=>req('/v1/generations',{method:'POST',body:JSON.stringify(data)});
const claim=req=>req('/agent/claim',{key:AGENT,method:'POST',body:JSON.stringify({ready:true})});

test('rejects missing/incorrect credentials and separates client/agent roles',()=>harness(async req=>{
 assert.equal((await req('/healthz',{key:''})).status,401);
 assert.equal((await req('/agent/claim',{key:CLIENT,method:'POST',body:'{}'})).status,401);
 assert.equal((await req('/healthz',{key:AGENT})).status,401);
 assert.equal((await req('/healthz')).status,200);
}));
test('rejects arbitrary forwarding fields and invalid generation parameters',()=>harness(async req=>{
 for(const data of [{prompt:'x',url:'http://internal/'},{prompt:'x',command:'id'},{prompt:'x',steps:21},{prompt:'x',width:257},{prompt:''}])assert.equal((await submit(req,data)).status,422);
}));
test('bounds queue, grants one lease, preserves PNG and hides lease from clients',()=>harness(async req=>{
 const first=await submit(req);assert.equal(first.status,202);const job=await first.json();
 assert.equal((await submit(req,{prompt:'second'})).status,202);
 assert.equal((await submit(req,{prompt:'third'})).status,429);
 const leased=(await (await claim(req)).json()).job;assert.equal(leased.id,job.id);
 assert.equal((await (await claim(req)).json()).job,null);
 const status=await (await req(job.status_url)).json();assert.equal(status.status,'RUNNING');assert.equal('lease' in status,false);
 assert.equal((await req(job.status_url+'/image')).status,409);
 const complete='/agent/jobs/'+job.id+'/complete';
 assert.equal((await req(complete,{key:AGENT,method:'POST',headers:{'X-Lease-Token':'wrong'},body:png})).status,409);
 const done=await req(complete,{key:AGENT,method:'POST',headers:{'X-Lease-Token':leased.lease,'X-Generation-Metadata':'{"fixture":true}'},body:png});assert.equal(done.status,200);
 const result=await req(job.status_url+'/image');assert.equal(result.status,200);assert.deepEqual(Buffer.from(await result.arrayBuffer()),png);
 const summary=await (await req(job.status_url)).json();assert.equal(summary.status,'SUCCEEDED');assert.equal(summary.metadata.fixture,true);
 assert.equal((await req(complete,{key:AGENT,method:'POST',headers:{'X-Lease-Token':leased.lease},body:png})).status,200);
 const altered=Buffer.from(png);altered[altered.length-1]^=1;
 assert.equal((await req(complete,{key:AGENT,method:'POST',headers:{'X-Lease-Token':leased.lease},body:altered})).status,409);
}));
test('invalid PNG cannot complete a task; failure remains visible',()=>harness(async req=>{
 const job=await (await submit(req)).json();const leased=(await (await claim(req)).json()).job;
 assert.equal((await req('/agent/jobs/'+job.id+'/complete',{key:AGENT,method:'POST',headers:{'X-Lease-Token':leased.lease},body:'not a PNG'})).status,422);
 assert.equal((await req('/agent/jobs/'+job.id+'/fail',{key:AGENT,method:'POST',headers:{'X-Lease-Token':leased.lease},body:JSON.stringify({error:'controlled test failure'})})).status,200);
 const result=await (await req(job.status_url)).json();assert.equal(result.status,'FAILED');assert.equal(result.error,'controlled test failure');
}));

test('daily application budget stops the 21st generation',()=>harness(async req=>{
 for(let i=0;i<20;i++){
  const result=await submit(req,{prompt:'budget test '+i});assert.equal(result.status,202);const job=await result.json();const leased=(await (await claim(req)).json()).job;
  assert.equal((await req('/agent/jobs/'+job.id+'/fail',{key:AGENT,method:'POST',headers:{'X-Lease-Token':leased.lease},body:'{"error":"budget fixture"}'})).status,200);
 }
 assert.equal((await submit(req,{prompt:'over limit'})).status,429);
}));

test('resource view needs client auth, reports timestamp and filters unapproved fields',()=>harness(async req=>{
 assert.equal((await req('/v1/system')).status,503);
 const snapshot={sampled_at:Date.now()/1000,cpu:{quota_cores:4,visible_cores:5,quota_usage_percent:25},memory:{limit_bytes:16000,used_bytes:6000,quota_headroom_bytes:10000},disk:{total_bytes:32000,used_bytes:10000,free_bytes:22000},model:{state:'READY',rss_bytes:5500},api:{uptime_seconds:60,lease_remaining_seconds:10000},env:{SECRET:'must never forward'},capabilities:{vm_create:true}};
 assert.equal((await req('/agent/heartbeat',{key:AGENT,method:'POST',body:JSON.stringify({ready:true,system:snapshot})})).status,200);
 const response=await req('/v1/system');assert.equal(response.status,200);const result=await response.json();
 assert.equal(result.cpu.quota_cores,4);assert.equal(result.agent_recent,true);assert.equal(result.capabilities.vm_create,false);
 assert.equal(JSON.stringify(result).includes('must never forward'),false);assert.ok(result.snapshot_age_seconds>=0);
}));
