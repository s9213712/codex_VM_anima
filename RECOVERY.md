# Recovery

See [VM recovery](docs/VM_GUIDE.md#7-暫停程序停止與重建) and [Windows backups](docs/WINDOWS_GUIDE.md#7-歷史圖片與備份).

Git recovers code only. Cloudflare retains job data for approximately 24 hours. Windows stores only history/PNGs already retrieved. None of these restore a lost VM private key or in-flight latent automatically.

Keep .private and history-data outside the source checkout. App updater mode3 restores backed-up local source files, not Cloudflare deployment or node_modules. For Cloudflare rollback, choose a deliberately reviewed known-good Git version in a separate checkout and deploy it with the same account and existing keys; do not force-reset the normal working tree or claim a failed deployment automatically rolled back remotely.

Never restart API while generating unless the owner explicitly accepts interruption. On a fresh VM, clone, reinstall, generate a new pairing tool and securely pair. Expired jobs require explicit owner resubmission, with no automatic paid fallback.
