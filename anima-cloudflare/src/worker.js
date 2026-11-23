import UI_HTML from "./ui.html";
const JSON_HEADERS = {"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store","X-Content-Type-Options":"nosniff"};
// 代理存活與任務逾時策略（毫秒）
const AGENT_SOFT_MS=90000;      // 超過 90 秒沒心跳：仍收單，但標記等待代理
const AGENT_HARD_MS=300000;     // 超過 5 分鐘：直接拒絕新單
const LEASE_MS=900000;          // 15 分鐘租約（原本 35 分鐘）
const PENDING_MAX_MS=600000;    // 卡在 PENDING 超過 10 分鐘 → FAILED
function agentGate(ageMs){
  if(ageMs===null||ageMs===undefined||!Number.isFinite(ageMs))return "reject";
  if(ageMs>AGENT_HARD_MS)return "reject";
  if(ageMs>AGENT_SOFT_MS)return "queue";
  return "ok";
}
const ID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
class HttpError extends Error { constructor(status,message) {super(message);this.status=status;} }
const json=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:JSON_HEADERS});

async function authenticate(request,key) {
  if (!key || key.length<32) throw new HttpError(503,"Relay secrets not configured");
  const header=request.headers.get("Authorization") || "";
  const token=header.startsWith("Bearer ")?header.slice(7):"";
  if (token.length!==key.length) throw new HttpError(401,"Bearer key required");
  const encode=new TextEncoder();
  const [a,b]=await Promise.all([crypto.subtle.digest("SHA-256",encode.encode(token)),crypto.subtle.digest("SHA-256",encode.encode(key))]);
  let difference=0; const aa=new Uint8Array(a),bb=new Uint8Array(b);
  for(let i=0;i<aa.length;i++)difference|=aa[i]^bb[i];
  if(difference)throw new HttpError(401,"Invalid key");
}
async function bytes(request,limit) {
  if(Number(request.headers.get("Content-Length") || 0)>limit)throw new HttpError(413,"Body too large");
  if(!request.body)return new Uint8Array();
  const reader=request.body.getReader(),parts=[];let total=0;
  for(;;){const {done,value}=await reader.read();if(done)break;total+=value.length;
    if(total>limit){await reader.cancel();throw new HttpError(413,"Body too large");}parts.push(value);}
  const result=new Uint8Array(total);let offset=0;for(const part of parts){result.set(part,offset);offset+=part.length;}return result;
}
async function bodyJSON(request,limit=8192){try{return JSON.parse(new TextDecoder().decode(await bytes(request,limit)));}catch(e){if(e instanceof HttpError)throw e;throw new HttpError(400,"Invalid JSON");}}
function validJob(input){
  if(!input || typeof input!=="object" || Array.isArray(input))throw new HttpError(422,"Expected a job object");
  if(typeof input.prompt!=="string" || !input.prompt.trim() || input.prompt.length>1500)throw new HttpError(422,"prompt must contain 1..1500 characters");
  const job={prompt:input.prompt,negative_prompt:input.negative_prompt??"low quality, blurry",width:input.width??256,height:input.height??256,steps:input.steps??8,seed:input.seed??42};
  if(typeof job.negative_prompt!=="string" || job.negative_prompt.length>1000)throw new HttpError(422,"negative_prompt too long");
  for(const field of ["width","height"])if(!Number.isInteger(job[field])||job[field]<128||job[field]>1024||job[field]%32)throw new HttpError(422,"Dimensions must be 128..1024 and multiples of 32");
  if(!Number.isInteger(job.steps)||job.steps<1||job.steps>20)throw new HttpError(422,"steps must be 1..20");
  if(!Number.isInteger(job.seed)||job.seed<0||job.seed>4294967295)throw new HttpError(422,"Invalid seed");
  // Reject data that could turn this application relay into arbitrary URL/command forwarding.
  if(Object.keys(input).some(k=>!Object.hasOwn(job,k)))throw new HttpError(422,"Unknown job field");
  return job;
}
function safeMetrics(value){
  if(!value || typeof value!=="object")return null;
  const number=x=>typeof x==='number'&&Number.isFinite(x)?x:null;
  return {sampled_at:number(value.sampled_at),cpu:{visible_cores:number(value.cpu?.visible_cores),quota_cores:number(value.cpu?.quota_cores),quota_usage_percent:number(value.cpu?.quota_usage_percent)},
    memory:{limit_bytes:number(value.memory?.limit_bytes),used_bytes:number(value.memory?.used_bytes),quota_headroom_bytes:number(value.memory?.quota_headroom_bytes)},
    disk:{total_bytes:number(value.disk?.total_bytes),used_bytes:number(value.disk?.used_bytes),free_bytes:number(value.disk?.free_bytes)},
    model:{state:['READY','LOADING','ERROR','STARTING'].includes(value.model?.state)?value.model.state:'UNKNOWN',rss_bytes:number(value.model?.rss_bytes),turbo_lora:value.model?.turbo_lora===true,lora_name:typeof value.model?.lora_name==='string'?value.model.lora_name.slice(0,80):null,guidance_scale:number(value.model?.guidance_scale),default_steps:number(value.model?.default_steps)},
    api:{uptime_seconds:number(value.api?.uptime_seconds),lease_remaining_seconds:number(value.api?.lease_remaining_seconds)},
    capabilities:{vm_create:false,vm_wake:false,inference_device:'cpu'}};
}
function publicJob(row){return {id:row.id,status:row.status,request:JSON.parse(row.request_json),created:row.created,started:row.started,finished:row.finished,
  error:row.error,metadata:row.metadata?JSON.parse(row.metadata):null,...(row.status==="SUCCEEDED"?{image_url:`/v1/jobs/${row.id}/image`}:{})};}

export default {
  async fetch(request,env){
    try{
      const path=new URL(request.url).pathname;
      if(path==="/ui" && request.method==="GET")return new Response(UI_HTML,{headers:{"Content-Type":"text/html; charset=utf-8","Cache-Control":"no-store"}});
      if(path==="/" && request.method==="GET"){
        if((request.headers.get("Accept")||"").includes("text/html"))return new Response(UI_HTML,{headers:{"Content-Type":"text/html; charset=utf-8","Cache-Control":"no-store"}});
        return json({build:"v2-liveness",service:"Anima HTTPS image-job relay",authentication:"Bearer required",ui:"/ui",docs:"POST /v1/generations, then poll returned status_url"});
      }
      await authenticate(request,path.startsWith("/agent/")?env.AGENT_KEY:env.CLIENT_KEY);
      return await env.RELAY.get(env.RELAY.idFromName(env.RELAY_INSTANCE || "single-approved-image-worker-v2")).fetch(request);
    }catch(e){return json({error:e instanceof HttpError?e.message:"Relay temporarily unavailable"},e instanceof HttpError?e.status:503);}
  }
};

export { authenticate, bytes, bodyJSON, validJob, safeMetrics, publicJob, agentGate, HttpError, json, AGENT_SOFT_MS, AGENT_HARD_MS, LEASE_MS, PENDING_MAX_MS };

export class AnimaRelayV2 {

  constructor(ctx,env){
    this.ctx=ctx;this.env=env;this.sql=ctx.storage.sql;
    this.sql.exec("CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,status TEXT NOT NULL,request_json TEXT NOT NULL,created INTEGER NOT NULL,started INTEGER,finished INTEGER,lease TEXT,lease_until INTEGER,error TEXT,metadata TEXT,image BLOB)");
    this.sql.exec("CREATE INDEX IF NOT EXISTS jobs_pending ON jobs(status,created)");
    this.sql.exec("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)");
  }
  rows(query,...args){return this.sql.exec(query,...args).toArray();}
  async fetch(request){
    try{
      const now=Date.now(),path=new URL(request.url).pathname,method=request.method;
      this.sql.exec("DELETE FROM jobs WHERE created < ?",now-86400000);
      // 代理離線時卡住的任務：PENDING 超時即失敗，避免客戶端無限輪詢與配額浪費
      this.sql.exec("UPDATE jobs SET status='FAILED',finished=?,error='Agent offline before claim' WHERE status='PENDING' AND created < ?",now,now-PENDING_MAX_MS);
      this.sql.exec("DELETE FROM meta WHERE key LIKE 'progress:%' AND substr(key,10) NOT IN (SELECT id FROM jobs)");
      this.sql.exec("UPDATE jobs SET status='FAILED',finished=?,error='Worker lease expired; resubmit explicitly' WHERE status='RUNNING' AND lease_until < ?",now,now);
      if(path==="/healthz" && method==="GET"){
        const heartbeat=this.rows("SELECT value FROM meta WHERE key='agent'")[0];const agent=heartbeat?JSON.parse(heartbeat.value):null;
        const age=agent?Math.max(0,Math.round((now-agent.observed_at)/1000)):null;
        const pending=this.rows("SELECT count(*) AS n FROM jobs WHERE status='PENDING'")[0].n;
        const running=this.rows("SELECT count(*) AS n FROM jobs WHERE status='RUNNING'")[0].n;
        const lastError=this.rows("SELECT error FROM jobs WHERE status='FAILED' AND error IS NOT NULL ORDER BY finished DESC LIMIT 1")[0]?.error ?? null;
        return json({relay:"READY",agent_recent:!!agent && now-agent.observed_at<60000,agent_age_seconds:age,
          pending,running,last_error:lastError,
          policy:{soft_queue_seconds:AGENT_SOFT_MS/1000,hard_reject_seconds:AGENT_HARD_MS/1000,lease_seconds:LEASE_MS/1000,pending_max_seconds:PENDING_MAX_MS/1000},
          agent});
      }
      if(path==="/v1/system" && method==="GET"){
        const entry=this.rows("SELECT value FROM meta WHERE key='agent'")[0];const agent=entry?JSON.parse(entry.value):null;
        if(!agent?.system)throw new HttpError(503,"No authenticated VM resource snapshot available yet");
        return json({...agent.system,snapshot_received_at:agent.observed_at,snapshot_age_seconds:agent.system.sampled_at===null?null:Math.max(0,(now/1000)-agent.system.sampled_at),agent_recent:now-agent.observed_at<60000});
      }
      if(path==="/v1/generations" && method==="POST"){
        const job=validJob(await bodyJSON(request));
        const hb=this.rows("SELECT value FROM meta WHERE key='agent'")[0];const hbAgent=hb?JSON.parse(hb.value):null;
        const gate=agentGate(hbAgent?now-hbAgent.observed_at:null);
        if(gate==="reject")throw new HttpError(503,"Agent offline; no fallback backend configured");
        const active=this.rows("SELECT count(*) AS n FROM jobs WHERE status IN ('PENDING','RUNNING')")[0].n;
        if(active>=2)throw new HttpError(429,"Queue full; retry after an existing task completes");
        const day=now-now%86400000;
        if(this.rows("SELECT count(*) AS n FROM jobs WHERE created>=?",day)[0].n>=20)throw new HttpError(429,"Daily application limit reached (20 jobs UTC)");
        const id=crypto.randomUUID();this.sql.exec("INSERT INTO jobs(id,status,request_json,created) VALUES(?,'PENDING',?,?)",id,JSON.stringify(job),now);
        return json({id,status:"PENDING",status_url:`/v1/jobs/${id}`,queued_while_agent_offline:gate==="queue"},202);
      }
      let match=path.match(new RegExp(`^/v1/jobs/(${ID})(/image)?$`));
      if(match && method==="GET"){
        const row=this.rows("SELECT * FROM jobs WHERE id=?",match[1])[0];if(!row)throw new HttpError(404,"Job not found");
        if(match[2]){
          if(row.status!=="SUCCEEDED")throw new HttpError(409,"Image not ready");
          return new Response(row.image,{headers:{"Content-Type":"image/png","Cache-Control":"no-store","X-Content-Type-Options":"nosniff","Content-Disposition":`attachment; filename="${row.id}.png"`}});
        }
        const progress=this.rows("SELECT value FROM meta WHERE key=?",'progress:'+row.id)[0];return json({...publicJob(row),progress:progress?JSON.parse(progress.value):null});
      }
      if((path==="/agent/claim" || path==="/agent/heartbeat") && method==="POST"){
        const input=await bodyJSON(request,2048);
        this.sql.exec("INSERT OR REPLACE INTO meta(key,value) VALUES('agent',?)",JSON.stringify({observed_at:now,ready:input.ready===true,busy:input.busy===true,model:"Anima CPU",system:safeMetrics(input.system)}));
        if(path==="/agent/heartbeat")return json({ok:true});
        if(input.ready!==true)return json({job:null});
        if(this.rows("SELECT id FROM jobs WHERE status='RUNNING' LIMIT 1").length)return json({job:null});
        const row=this.rows("SELECT * FROM jobs WHERE status='PENDING' ORDER BY created,id LIMIT 1")[0];if(!row)return json({job:null});
        const lease=crypto.randomUUID();this.sql.exec("UPDATE jobs SET status='RUNNING',started=?,lease=?,lease_until=? WHERE id=?",now,lease,now+LEASE_MS,row.id);
        return json({job:{id:row.id,request:JSON.parse(row.request_json),lease,lease_until:now+LEASE_MS}});
      }
      match=path.match(new RegExp(`^/agent/jobs/(${ID})/progress$`));
      if(match && method==='POST'){
        const data=await bodyJSON(request,12000);
        const row=this.rows('SELECT * FROM jobs WHERE id=?',match[1])[0];
        if(!row || row.status!=='RUNNING' || row.lease!==request.headers.get('X-Lease-Token') || row.lease_until<now)throw new HttpError(409,'Invalid progress lease');
        const total=JSON.parse(row.request_json).steps;
        if(!['ENCODING','DENOISING','DECODING','SAVING'].includes(data.stage)||!Number.isInteger(data.step)||data.step<0||data.step>total||!Number.isFinite(data.elapsed_seconds)||data.elapsed_seconds<0)throw new HttpError(422,'Invalid progress');
        this.sql.exec('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)','progress:'+row.id,JSON.stringify({stage:data.stage,step:data.step,total,elapsed_seconds:data.elapsed_seconds,updated_at:now/1000,log_tail:typeof data.log_tail==='string'?data.log_tail.slice(-8192):''}));
        this.sql.exec('UPDATE jobs SET lease_until=? WHERE id=?',now+120000,row.id);
        return json({ok:true});
      }
      match=path.match(new RegExp(`^/agent/jobs/(${ID})/(complete|fail)$`));
      if(match && method==="POST"){
        const id=match[1],action=match[2];
        // Read network payload before checking the lease again; no async gaps during state mutation.
        let content,metadata,error;
        if(action==="complete"){
          content=await bytes(request,2*1024*1024);
          if(content.length<8 || [137,80,78,71,13,10,26,10].some((x,i)=>content[i]!==x))throw new HttpError(422,"Expected PNG bytes");
          const header=request.headers.get('X-Generation-Metadata')||'{}';if(header.length>2048)throw new HttpError(422,"Metadata too large");
          try{metadata=JSON.parse(header);}catch{throw new HttpError(422,"Invalid metadata");}
          if(!metadata || typeof metadata!=='object' || Array.isArray(metadata))throw new HttpError(422,'Metadata must be an object');
          const digest=await crypto.subtle.digest('SHA-256',content);metadata.sha256=Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,'0')).join('');
        }else{const data=await bodyJSON(request,4096);error=String(data.error||'Generation failed').slice(0,2000);}
        const row=this.rows("SELECT * FROM jobs WHERE id=?",id)[0];if(!row)throw new HttpError(404,"Job not found");
        if(row.lease!==request.headers.get('X-Lease-Token'))throw new HttpError(409,"Lease token mismatch");
        if(row.status==='SUCCEEDED' && action==='complete'){
          if(JSON.parse(row.metadata).sha256!==metadata.sha256)throw new HttpError(409,'Result already committed with different bytes');
          return json({ok:true,idempotent:true});
        }
        if(row.status!=='RUNNING'||row.lease_until<Date.now())throw new HttpError(409,"Lease expired or task already terminal");
        if(action==='complete')this.sql.exec("UPDATE jobs SET status='SUCCEEDED',finished=?,metadata=?,image=? WHERE id=?",Date.now(),JSON.stringify(metadata),content.buffer,id);
        else this.sql.exec("UPDATE jobs SET status='FAILED',finished=?,error=? WHERE id=?",Date.now(),error,id);
        return json({ok:true});
      }
      throw new HttpError(404,"Unknown application endpoint");
    }catch(e){return json({error:e instanceof HttpError?e.message:"Relay storage operation failed"},e instanceof HttpError?e.status:503);}
  }
}
