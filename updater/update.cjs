'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),cp=require('node:child_process'),readline=require('node:readline/promises');
const ROOT=__dirname, VERSION='2026.11.23-git';
function hash(b){return crypto.createHash('sha256').update(b).digest('hex')}
function readJSON(p){return JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''))}
function validateRoot(root){
 if(!fs.statSync(root).isDirectory()||!fs.existsSync(path.join(root,'.private','client.key')))throw Error('Select the existing anima-cloudflare folder containing .private/client.key. No keys will be created or replaced.');
 for(const part of ['anima-client','.private','src']){const p=path.join(root,part);if(fs.existsSync(p)&&fs.lstatSync(p).isSymbolicLink())throw Error('Refusing symbolic-link installation directory: '+part)}
}
function payload(){
 const manifest=readJSON(path.join(ROOT,'manifest.json'));
 for(const [name,digest] of Object.entries(manifest.files)){
  if(!/^(client|relay)\/[A-Za-z0-9_.\/-]+$/.test(name)||name.split('/').includes('..'))throw Error('Invalid manifest path');
  if(hash(fs.readFileSync(path.join(ROOT,'payload',name)))!==digest)throw Error('Package integrity check failed: '+name);
 }
 return manifest;
}
function targets(root,manifest,relay){
 return Object.keys(manifest.files).filter(n=>relay||n.startsWith('client/')).map(n=>({source:path.join(ROOT,'payload',n),target:path.join(root,n.startsWith('client/')?'anima-client/'+n.slice(7):n.slice(6))}));
}
function backup(root,files){
 const dir=path.join(root,'.update-backups',new Date().toISOString().replace(/[:.]/g,'-'));
 fs.mkdirSync(dir,{recursive:true});const records=[];
 for(const f of files){const rel=path.relative(root,f.target);if(fs.existsSync(f.target)&&fs.lstatSync(f.target).isSymbolicLink())throw Error('Refusing symlink file');const existed=fs.existsSync(f.target);if(existed){const out=path.join(dir,rel);fs.mkdirSync(path.dirname(out),{recursive:true});fs.copyFileSync(f.target,out)}records.push({rel,existed})}
 fs.writeFileSync(path.join(dir,'records.json'),JSON.stringify(records));return dir;
}
function restore(root,dir){
 for(const r of readJSON(path.join(dir,'records.json'))){const dst=path.resolve(root,r.rel);if(!dst.startsWith(path.resolve(root)+path.sep)||r.rel.split(/[\\/]/).includes('.private'))throw Error('Unsafe rollback path');if(r.existed){fs.mkdirSync(path.dirname(dst),{recursive:true});fs.copyFileSync(path.join(dir,r.rel),dst)}else if(fs.existsSync(dst))fs.unlinkSync(dst)}
}
function apply(files){for(const f of files){fs.mkdirSync(path.dirname(f.target),{recursive:true});const tmp=f.target+'.update-tmp';fs.copyFileSync(f.source,tmp);fs.renameSync(tmp,f.target)}}
function run(cmd,args,cwd){const p=cp.spawnSync(cmd,args,{cwd,stdio:'inherit',shell:false,env:{...process.env,WRANGLER_SEND_METRICS:'false',CI:'true'}});if(p.error)throw p.error;if(p.status!==0)throw Error('Command failed: '+path.basename(cmd)+' (exit '+p.status+')')}
function npmInstall(root){
 // Execute npm's JS entry directly: no cmd.exe interpolation or quoted JS arguments.
 const nodeDir=path.dirname(process.execPath),npmCLI=path.join(nodeDir,'node_modules','npm','bin','npm-cli.js');
 if(!fs.existsSync(npmCLI))throw Error('Official Node.js/npm installation not found; install Node.js LTS.');
 run(process.execPath,[npmCLI,'ci','--ignore-scripts'],root);
}
function wrangler(root,args){run(process.execPath,[path.join(root,'node_modules','wrangler','bin','wrangler.js'),...args],root)}
async function health(root){
 const key=fs.readFileSync(path.join(root,'.private','client.key'),'utf8').trim();let url='https://anima.s92137123.workers.dev';
 const stored=path.join(root,'.private','relay-url.txt');if(fs.existsSync(stored))url=fs.readFileSync(stored,'utf8').trim();
 if(!/^https:\/\/anima\.[a-z0-9-]+\.workers\.dev$/.test(url))throw Error('Unexpected saved relay URL');
 const r=await fetch(url+'/healthz',{headers:{Authorization:'Bearer '+key},redirect:'error',signal:AbortSignal.timeout(30000)});
 if(r.status!==200||(await r.json()).relay!=='READY')throw Error('Authenticated relay health check failed');
 const bad=await fetch(url+'/healthz',{headers:{Authorization:'Bearer wrong-key'},redirect:'error',signal:AbortSignal.timeout(30000)});if(bad.status!==401)throw Error('Wrong-key rejection check failed');
 console.log('PASS: Cloudflare health=200; wrong key=401. '+url);
}
async function main(){
 const unattended=process.argv.includes('--unattended');
 const manifest=payload();let root=process.argv.includes('--target')?process.argv[process.argv.indexOf('--target')+1]:null;
 if(!root){const here=path.join(ROOT,'..');if(fs.existsSync(path.join(here,'.private','client.key')))root=here;else{
  const p=cp.spawnSync('powershell.exe',['-NoProfile','-STA','-ExecutionPolicy','Bypass','-File',path.join(ROOT,'select-folder.ps1')],{encoding:'utf8',shell:false});if(p.status!==0)throw Error('Folder selection canceled');root=p.stdout.trim();
 }}
 root=path.resolve(root);validateRoot(root);
 const rl=readline.createInterface({input:process.stdin,output:process.stdout});let dir;
 try{
  console.log('Anima updater '+VERSION+'\nTarget: '+root+'\nClose the old Anima CLIENT console before updating. Keep the VM running.');
  const mode=unattended?'2':await rl.question('1 = client only; 2 = client + Cloudflare (recommended); 3 = restore last local backup. Choose [2]: ');
  if(mode==='3'){
   const base=path.join(root,'.update-backups');const dirs=fs.existsSync(base)?fs.readdirSync(base).filter(n=>fs.existsSync(path.join(base,n,'records.json'))).sort():[];if(!dirs.length)throw Error('No backup found');restore(root,path.join(base,dirs.at(-1)));console.log('Local files restored. This does not roll back the deployed Cloudflare Worker.');return;
  }
  if(mode && !['1','2'].includes(mode))throw Error('Unknown selection');
  const relay=mode!=='1';
  if(relay){const cfg=readJSON(path.join(root,'wrangler.jsonc'));if(cfg.name!=='anima'||!/^[0-9a-fA-F]{32}$/.test(cfg.account_id||''))throw Error('Existing anima Worker account configuration missing. This updater does not initialize or change accounts.');
   if(!unattended){const answer=await rl.question('Confirm account is still Workers Free and update ONLY anima? [y/N]: ');if(answer.toLowerCase()!=='y')throw Error('Deployment canceled');}
   console.log('Using existing anima account authorization; no plan changes or credential rotation.');
  }
  const files=targets(root,manifest,relay);dir=backup(root,files);
  try{apply(files)}catch(e){restore(root,dir);throw e}
  console.log('Local files backed up. Credentials and connection.json preserved.');
  if(relay){
   npmInstall(root);
   // Reuse existing OAuth only. CI prevents interactive authorization during routine updates.
   wrangler(root,['deploy','--dry-run','--outdir','.dry-run']);
   wrangler(root,['deploy']);
   await health(root);
  }
  const connection=path.join(root,'anima-client','connection.json');
  if(!fs.existsSync(connection)){
   const urlFile=path.join(root,'.private','relay-url.txt');
   if(!fs.existsSync(urlFile))throw Error('Saved relay URL is missing. Complete first deployment verification before initial client setup.');
   const api=fs.readFileSync(urlFile,'utf8').trim();
   if(!/^https:\/\/anima\.[a-z0-9-]+\.workers\.dev$/.test(api))throw Error('Unexpected saved relay URL');
   fs.writeFileSync(connection,JSON.stringify({backend:'http',api,key_file:'../.private/client.key',codex_environment_id:''},null,2));
  }
  console.log('DONE. Double-click anima-client/start-windows.bat to open the updated client.');
  console.log('Backup: '+dir+'\nNo VM restart or paid upgrade was requested. Keep backups until verified; no automatic deletion.');
 }catch(e){if(dir)console.error('Backup retained: '+dir+'. Remote deployment may have changed; no remote rollback is claimed.');throw e}finally{rl.close()}
}
if(require.main===module)main().catch(e=>{console.error('STOP: '+e.message);process.exitCode=1});
module.exports={main,payload,validateRoot,targets,backup,restore,apply};
