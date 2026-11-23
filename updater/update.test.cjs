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
