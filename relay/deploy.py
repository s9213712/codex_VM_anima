"""Deploy only this reviewed image relay, on a user-confirmed Workers Free account."""
import json,os,re,secrets,subprocess,time
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1];HERE=ROOT/'relay';STATE=ROOT/'.state'

def main():
    approval=STATE/'relay-free-plan-approval.json'
    approved=os.environ.get('CLOUDFLARE_FREE_PLAN_CONFIRMED')=='true' or (approval.exists() and json.loads(approval.read_text()).get('confirmed') is True)
    if not approved:raise RuntimeError('BLOCKED: owner must confirm this Account ID is on Workers Free; paid resources are never enabled automatically')
    token=os.environ.get('CLOUDFLARE_API_TOKEN');account=os.environ.get('CLOUDFLARE_ACCOUNT_ID','')
    if not token or not re.fullmatch(r'[0-9a-fA-F]{32}',account):raise RuntimeError('BLOCKED: configure CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID in Environment Secrets; never paste the token in chat')
    config=json.loads((HERE/'wrangler.jsonc').read_text());name=config['name']
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,50}',name):raise RuntimeError('Invalid worker script name')
    marker=STATE/'relay-deployment.json';owned=json.loads(marker.read_text()) if marker.exists() else {}
    with httpx.Client(base_url='https://api.cloudflare.com/client/v4',headers={'Authorization':'Bearer '+token},timeout=30) as c:
        verified=c.get('/user/tokens/verify');verified.raise_for_status()
        if not verified.json().get('success'):raise RuntimeError('Cloudflare token verification failed; review permissions in the dashboard')
        existing=c.get('/accounts/'+account+'/workers/scripts/'+name)
        if existing.status_code==200 and not (owned.get('account_id')==account and owned.get('script')==name):
            raise RuntimeError('Refusing to overwrite an existing unrelated Worker; choose an unused name in relay/wrangler.jsonc')
        if existing.status_code not in (200,404):existing.raise_for_status()
    # Generate independent application keys, not Cloudflare management credentials.
    keysfile=STATE/'relay-keys.json'
    if not keysfile.exists():
        keysfile.write_text(json.dumps({'CLIENT_KEY':secrets.token_urlsafe(32),'AGENT_KEY':secrets.token_urlsafe(32)}));keysfile.chmod(0o600)
    keys=json.loads(keysfile.read_text())
    for role,key in keys.items():
        if role not in ('CLIENT_KEY','AGENT_KEY') or not isinstance(key,str) or len(key)<32:raise RuntimeError('Invalid application key file')
    env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','LC_ALL','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','http_proxy','https_proxy','no_proxy','SSL_CERT_FILE','SSL_CERT_DIR','NODE_EXTRA_CA_CERTS'}}
    env.update(CLOUDFLARE_API_TOKEN=token,CLOUDFLARE_ACCOUNT_ID=account,CI='true',WRANGLER_SEND_METRICS='false',NODE_USE_ENV_PROXY='1',XDG_CONFIG_HOME=str(STATE/'wrangler-config'),XDG_CACHE_HOME=str(ROOT/'.cache/wrangler'),WRANGLER_LOG_PATH=str(STATE/'wrangler.log'))
    wrangler=str(HERE/'node_modules/.bin/wrangler')
    def invoke(args):
        p=subprocess.run([wrangler,*args,'--config',str(HERE/'wrangler.jsonc')],cwd=ROOT,env=env,text=True,capture_output=True,timeout=180)
        text=p.stdout+'\n'+p.stderr+'\n'
        for private in [token,*keys.values()]:text=text.replace(private,'[REDACTED]')
        with (STATE/'relay-deploy.log').open('a') as log:log.write(text)
        if p.returncode:raise RuntimeError('Cloudflare deployment step failed (exit '+str(p.returncode)+'); inspect the protected local deployment log')
        return p.stdout
    output=invoke(['deploy'])
    marker.write_text(json.dumps({'account_id':account,'script':name,'created_by_this_project':True,'deployed_at':time.time()},indent=2))
    invoke(['secret','bulk',str(keysfile)])
    candidates=re.findall(r'https://[a-z0-9.-]+\.workers\.dev\b',output)
    if not candidates:raise RuntimeError('Deployment returned no workers.dev URL; inspect local log; no public link claimed')
    url=candidates[0]
    # Preserve the normal HTTP proxy/CA. A denied runtime endpoint blocks deployment verification.
    with httpx.Client(base_url=url,timeout=30,headers={'Authorization':'Bearer '+keys['CLIENT_KEY']}) as c:
        r=c.get('/healthz');r.raise_for_status()
        if r.json().get('relay')!='READY':raise RuntimeError('Deployed relay did not report ready')
        rejected=c.get('/healthz',headers={'Authorization':'Bearer deliberately-invalid-verification-value'})
        if rejected.status_code!=401:raise RuntimeError('Public relay authentication verification failed')
    (STATE/'relay-public-url.txt').write_text(url)
    key=STATE/'relay-agent.key';key.write_text(keys['AGENT_KEY']);key.chmod(0o600)
    (STATE/'relay-public-deployment.json').write_text(json.dumps({'url':url,'verified_at':time.time(),'auth_rejected':401,'relay_health':200,'model_e2e':'PENDING'},indent=2))
    print('Authenticated relay verified:',url)
    print('Next: set ANIMA_RELAY_URL to this URL and ANIMA_RELAY_AGENT_KEY_FILE to .state/relay-agent.key, then run relay/agent.py.')
    print('Application keys remain in protected .state files; no management token was printed.')
if __name__=='__main__':main()
