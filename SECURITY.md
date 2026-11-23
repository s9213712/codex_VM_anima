# Security

This public repository contains application source and non-private synthetic test evidence, not runtime credentials or model weights. Never commit .private, .state, OAuth configurations, databases, history-data, personal prompts/images, .env or private PEM keys.

CLIENT_KEY and AGENT_KEY are separate roles. A user holding CLIENT_KEY can access this relay owner's jobs; this is not a multi-tenant per-user authorization service. Do not give a shared owner key to unrelated users.

Cloudflare sees prompts, logs and PNG data for this workflow. GitHub holds source only. The inference API binds localhost, validates a fixed image schema and never executes prompt-supplied shell commands/URLs. Treat model logs and external content as untrusted; browser text is rendered with textContent.

Local UI requires localhost Host/Origin and an unguessable session header. Cached history contains private prompts/images; protect the Windows account and application folder. PNG cache verifies known SHA256; packet/manifest hashes do not independently sign an update. Trust only the specified GitHub origin and reviewed branch.

Git updates use fast-forward only, preserve dirty source checkouts and retain local application backups. Routine updates reuse existing credentials, never rotate keys or upgrade billing plans. OAuth may expire or be revoked; failed authorization stops the update rather than bypassing it. Never put a credential into a Git remote URL.

Model/LoRA licenses remain applicable. No paid resources, public database or automatic main merge is provisioned. There is no uptime or VM-wake guarantee.

For accidental credential disclosure, revoke/replace the affected credential in its provider, then re-pair clients and VM deliberately. Removing a file from the latest commit does not erase Git history. Do not post security reports containing secrets as public Issues.
