# Cloudflare agent setup — 2026-11-23 UTC

Official instructions fetched from https://developers.cloudflare.com/agent-setup/prompt.md.

## Verified

- Installed 22 official Cloudflare skills into `/workspace/anima-server/.agents/skills` using `npm_config_cache=/workspace/anima-server/.cache/npm npx -y skills add cloudflare/skills --skill "*" --yes --agent codex`.
- Used project installation because the managed global configuration is read-only.
- Registered MCP with `CODEX_HOME=/workspace/cloudflare-codex codex mcp add cloudflare --url https://mcp.cloudflare.com/mcp`.
- `CODEX_HOME=/workspace/cloudflare-codex codex mcp list` reports cloudflare enabled, Auth Unknown.
- Registration initiated OAuth, but it is NOT authenticated. Callback uses VM localhost; no shared desktop/browser tool or preview is available. Do not treat a browser authorization click alone as successful VM authentication.
- This separate Codex CLI configuration does not inject MCP tools into the current hosted conversation. A compatible subsequent CLI session must use the same configuration directory.
- Optional beta cf CLI was skipped; project already has Wrangler configuration.
- No Worker deployment, paid resource activation, or billable API call was performed by this setup.

## Remaining

Complete OAuth in a usable local/shared browser environment, or configure the existing deployment script with Environment Secrets as documented in relay/README.md. Never paste authorization codes, callback URLs, API tokens or keys into chat. VM-local installation and auth storage are not guaranteed to survive recreation.
