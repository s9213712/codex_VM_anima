// Local integration runtime only; this does not create a public Cloudflare deployment.
import {Miniflare} from 'miniflare';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {randomBytes} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const state=path.join(root,'.state');await mkdir(state,{recursive:true,mode:0o700});
const keysPath=path.join(state,'relay-test-keys.json');let keys;
try{keys=JSON.parse(await readFile(keysPath,'utf8'));}catch{keys={CLIENT_KEY:randomBytes(32).toString('base64url'),AGENT_KEY:randomBytes(32).toString('base64url')};await writeFile(keysPath,JSON.stringify(keys),{mode:0o600});}
await writeFile(path.join(state,'relay-test-agent.key'),keys.AGENT_KEY,{mode:0o600});await writeFile(path.join(state,'relay-test-client.key'),keys.CLIENT_KEY,{mode:0o600});
const mf=new Miniflare({modules:true,script:await readFile(path.join(root,'relay/src/worker.js'),'utf8'),host:'127.0.0.1',port:8787,
 compatibilityDate:'2026-07-30',bindings:keys,durableObjects:{RELAY:{className:'AnimaRelay',useSQLite:true}},durableObjectsPersist:path.join(state,'relay-local-do')});
console.log('LOCAL_TEST_RELAY',String(await mf.ready));
let ending=false;
async function stop(){if(ending)return;ending=true;await mf.dispose();process.exit(0);}
process.on('SIGTERM',stop);process.on('SIGINT',stop);setTimeout(stop,900000);
