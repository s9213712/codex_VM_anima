// 純邏輯：可被單元測試直接匯入（不依賴 Worker runtime）
const JSON_HEADERS = {"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store","X-Content-Type-Options":"nosniff"};
// 代理存活與任務逾時策略（毫秒）
const AGENT_SOFT_MS=90000;      // 超過 90 秒沒心跳：仍收單，但標記等待代理
const AGENT_HARD_MS=300000;     // 超過 5 分鐘：直接拒絕新單
const RETENTION_MS=7*24*60*60*1000; // 任務保留 7 天
const LEASE_MS=900000;          // 15 分鐘租約（原本 35 分鐘）
const PENDING_MAX_MS=600000;    // 卡在 PENDING 超過 10 分鐘 → FAILED
function agentGate(ageMs){
  if(ageMs===null||ageMs===undefined||!Number.isFinite(ageMs))return "reject";
  if(ageMs>AGENT_HARD_MS)return "reject";
  if(ageMs>AGENT_SOFT_MS)return "queue";
  return "ok";
}
const FALLBACK_TIMEOUT_MS=300000;
function fallbackDecision(gate,fallbackConfigured){
  if(gate!=="reject")return "primary";
  return fallbackConfigured?"fallback":"reject";
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
function publicJob(row){return {id:row.id,status:row.status,backend:row.backend||"primary",request:JSON.parse(row.request_json),created:row.created,started:row.started,finished:row.finished,
  error:row.error,metadata:row.metadata?JSON.parse(row.metadata):null,...(row.status==="SUCCEEDED"?{image_url:`/v1/jobs/${row.id}/image`}:{})};}



export { ID, fallbackDecision, FALLBACK_TIMEOUT_MS, JSON_HEADERS, HttpError, json, authenticate, bytes, bodyJSON, validJob, safeMetrics, publicJob, agentGate,
  AGENT_SOFT_MS, AGENT_HARD_MS, LEASE_MS, PENDING_MAX_MS, RETENTION_MS };
