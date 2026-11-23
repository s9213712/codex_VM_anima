Anima Windows deployment (existing Worker: anima)

1. Install Node.js LTS from https://nodejs.org/ (22+).
2. Extract this entire ZIP to a normal folder. Do not run inside the ZIP.
3. Open PowerShell in that folder and run:
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Deploy-Anima.ps1
   Bypass applies to this invocation only; it does not permanently change policy.
4. Confirm your Cloudflare account is Workers Free. Enter FREE and your Account ID.
5. The official Wrangler login opens your browser. Review and authorize there.
6. Check whoami, type anima to authorize updating your existing anima Worker.
7. After deployment, paste the printed workers.dev URL into the terminal when asked.

This deploys the real relay, SQLite migration and RELAY binding, then creates
independent CLIENT_KEY/AGENT_KEY secrets and checks health=200, wrong key=401.
The script does not upgrade plans, buy resources or provision a VM.
Wrangler OAuth may request broad account permissions; review before approving.
Do not authorize if it selects the wrong account. Re-running preserves app keys.
Do not delete .private; new keys would disconnect existing clients/agents.
Never upload .private, OAuth credentials, keys, or node_modules to chat or Git.

IMPORTANT: Successful relay deployment is not successful image generation.
The Codex VM still needs the relay URL and agent.key via a secure transfer
mechanism. This ZIP cannot wake that VM or securely transfer that key by itself.
Report only the public Worker URL and PASS/error text. Hide secrets in screenshots.
The final client and end-to-end generation check follow VM pairing.

Linux bundling/dry-run checks do not constitute Windows execution verification.
