// Only this VM can decrypt the output. Never print or send the plaintext key.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const dir = __dirname;
const keyPath = path.resolve(dir, '..', '.private', 'agent.key');
if (!fs.existsSync(keyPath)) throw new Error('Place vm-pairing inside your deployed anima-cloudflare folder, next to .private.');
const agentKey = fs.readFileSync(keyPath, 'utf8').trim();
if (agentKey.length < 32 || agentKey.length > 128) throw new Error('Invalid agent.key');
const payload = JSON.stringify({url:'https://anima.s92137123.workers.dev',agent_key:agentKey});
const publicKey = fs.readFileSync(path.join(dir,'vm-public.pem'));
const ciphertext = crypto.publicEncrypt({key:publicKey, padding:crypto.constants.RSA_PKCS1_OAEP_PADDING,oaepHash:'sha256'},Buffer.from(payload));
const fingerprint = crypto.createHash('sha256').update(publicKey).digest('hex');
const out = path.join(dir,'vm-pairing.encrypted.json');
fs.writeFileSync(out,JSON.stringify({version:1,algorithm:'RSA-OAEP-SHA256',public_key_sha256:fingerprint,ciphertext:ciphertext.toString('base64')},null,2));
console.log('Created encrypted pairing file: '+out);
console.log('Upload ONLY vm-pairing.encrypted.json to this conversation.');
console.log('Never upload .private, agent.key, client.key or relay-keys.json.');
