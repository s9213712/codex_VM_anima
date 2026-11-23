'use strict';
// This file runs in a clean source checkout; installed files live elsewhere.
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process');
const repo=path.resolve(__dirname,'..'),branch='work/anima-restore';
const gitArgs=[];
function git(args,capture=false){const r=cp.spawnSync('git',[...gitArgs,'-C',repo,...args],{encoding:'utf8',stdio:capture?'pipe':'inherit',shell:false,env:{...process.env,GIT_TERMINAL_PROMPT:'0'}});if(r.error)throw r.error;if(r.status!==0)throw Error('Git operation failed. No reset, merge resolution or force push was attempted.');return capture?r.stdout.trim():''}
function main(){
 const origin=git(['remote','get-url','origin'],true);
 if(!['https://github.com/s9213712/codex_VM_anima','https://github.com/s9213712/codex_VM_anima.git','git@github.com:s9213712/codex_VM_anima.git'].includes(origin))throw Error('Origin is not the approved repository.');
 if(git(['branch','--show-current'],true)!==branch)throw Error('Switch to '+branch+' before updating.');
 git(['diff','--exit-code','--quiet']);git(['diff','--cached','--exit-code','--quiet']);
 console.log('Fetching approved GitHub source using existing Git credentials if needed. No interactive login will be started.');
 git(['fetch','origin',branch]);git(['merge','--ff-only','origin/'+branch]);
 console.log('Source commit: '+git(['rev-parse','--short','HEAD'],true));
 // Launch updated installer as a separate process, so this wrapper is not re-evaluated mid-update.
 const storage=path.join(process.env.LOCALAPPDATA||process.env.XDG_STATE_HOME||repo,'AnimaUpdater');
 const saved=path.join(storage,'installation.json');let target;
 if(fs.existsSync(saved)){
  try{target=JSON.parse(fs.readFileSync(saved,'utf8')).target;if(!fs.existsSync(path.join(target,'.private/client.key')))target=null}catch{target=null}
 }
 if(!target){
  const pick=cp.spawnSync('powershell.exe',['-NoProfile','-STA','-ExecutionPolicy','Bypass','-File',path.join(repo,'updater/select-folder.ps1')],{encoding:'utf8',shell:false});
  if(pick.status!==0)throw Error('Folder selection canceled.');target=pick.stdout.trim();
 }
 if(path.resolve(target)===repo||path.resolve(target).startsWith(repo+path.sep))throw Error('Choose your installed app outside this Git checkout.');
 const result=cp.spawnSync(process.execPath,[path.join(repo,'updater/update.cjs'),'--target',target,'--unattended'],{stdio:'inherit',shell:false});
 if(result.error)throw result.error;if(result.status!==0)throw Error('Application update did not complete. Source was fetched; existing credentials remain untouched.');
 fs.mkdirSync(storage,{recursive:true});fs.writeFileSync(saved,JSON.stringify({target}));
}
if(require.main===module)try{main()}catch(e){console.error('STOP: '+e.message);process.exitCode=1}
