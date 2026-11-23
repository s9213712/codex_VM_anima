const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const u=require('./update.cjs');
test('package integrity and backup rollback preserve original credentials and connection settings',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'anima-update-'));
 try{
  fs.mkdirSync(path.join(root,'.private'));fs.mkdirSync(path.join(root,'anima-client'));
  fs.writeFileSync(path.join(root,'.private/client.key'),'test-secret-must-remain');
  fs.writeFileSync(path.join(root,'anima-client/connection.json'),'original-settings');
  fs.writeFileSync(path.join(root,'anima-client/dashboard.py'),'original-client');
  u.validateRoot(root);const m=u.payload(),files=u.targets(root,m,false);
  assert.ok(files.every(f=>f.target.includes('anima-client')));
  const b=u.backup(root,files);u.apply(files);
  assert.notEqual(fs.readFileSync(path.join(root,'anima-client/dashboard.py'),'utf8'),'original-client');
  assert.equal(fs.readFileSync(path.join(root,'.private/client.key'),'utf8'),'test-secret-must-remain');
  assert.equal(fs.readFileSync(path.join(root,'anima-client/connection.json'),'utf8'),'original-settings');
  assert.ok(!fs.existsSync(path.join(b,'.private')));
  u.restore(root,b);
  assert.equal(fs.readFileSync(path.join(root,'anima-client/dashboard.py'),'utf8'),'original-client');
  assert.ok(!fs.existsSync(path.join(root,'anima-client/dashboard.html')));
  assert.equal(fs.readFileSync(path.join(root,'.private/client.key'),'utf8'),'test-secret-must-remain');
 }finally{fs.rmSync(root,{recursive:true,force:true})}
});
test('refuses updating an unrelated folder without existing credentials',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'anima-invalid-'));
 try{assert.throws(()=>u.validateRoot(root),/existing anima-cloudflare/)}finally{fs.rmSync(root,{recursive:true,force:true})}
});

test('Git unattended update reuses credentials, asks no questions and starts no OAuth login',async()=>{
 const cp=require('node:child_process');
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'anima-unattended-'));
 const oldExec=process.execPath,oldArgv=process.argv,oldSpawn=cp.spawnSync,oldFetch=global.fetch;
 const calls=[];
 try{
  fs.mkdirSync(path.join(root,'.private'));fs.mkdirSync(path.join(root,'fake-node/node_modules/npm/bin'),{recursive:true});
  fs.writeFileSync(path.join(root,'fake-node/node_modules/npm/bin/npm-cli.js'),'');
  fs.writeFileSync(path.join(root,'.private/client.key'),'test-only-key');
  fs.writeFileSync(path.join(root,'.private/agent.key'),'test-only-agent-key');
  fs.writeFileSync(path.join(root,'.private/relay-url.txt'),'https://anima.example.workers.dev');
  fs.writeFileSync(path.join(root,'wrangler.jsonc'),JSON.stringify({name:'anima',account_id:'a'.repeat(32)}));
  process.execPath=path.join(root,'fake-node/node.exe');process.argv=['node','update.cjs','--target',root,'--unattended'];
  cp.spawnSync=(command,args)=>{calls.push([command,...args]);return {status:0}};
  global.fetch=async(url,options)=>options.headers.Authorization==='Bearer wrong-key'?new Response('',{status:401}):Response.json({relay:'READY'});
  await u.main();
  assert.equal(fs.readFileSync(path.join(root,'.private/agent.key'),'utf8'),'test-only-agent-key');
  assert.equal(fs.readFileSync(path.join(root,'.private/client.key'),'utf8'),'test-only-key');
  assert.equal(JSON.parse(fs.readFileSync(path.join(root,'anima-client/connection.json'),'utf8')).api,'https://anima.example.workers.dev');
  assert.ok(calls.some(call=>call.includes('deploy')));
  assert.ok(!calls.some(call=>call.includes('login')||call.includes('secret')));
 }finally{process.execPath=oldExec;process.argv=oldArgv;cp.spawnSync=oldSpawn;global.fetch=oldFetch;fs.rmSync(root,{recursive:true,force:true})}
});
