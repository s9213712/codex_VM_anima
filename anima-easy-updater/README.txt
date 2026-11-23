Anima simple updater — 2026.11.23-turbo8

1. Close the old client PowerShell/console window. Do not stop the VM.
2. Extract this ZIP anywhere. Double-click Update-Anima.bat.
3. Select your ORIGINAL anima-cloudflare folder (the one with .private).
4. Press Enter for client + Cloudflare; enter y to confirm your account is
   still Workers Free and authorize updating only the existing anima Worker.
5. If needed, authorize the official Wrangler login in your own browser.
6. Wait for DONE, then double-click anima-client/start-windows.bat as usual.

No PowerShell commands to copy; no Account ID or URL to retype.
Requires the Node.js 22+ and existing deployment already configured earlier.
Does not create or rotate credentials. Keeps .private, connection.json,
wrangler.jsonc, VM pairing, downloaded images and unrelated files unchanged.
Source packages are bundled in this ZIP; it never downloads arbitrary update
scripts. npm downloads pinned dependencies from package-lock.json.
Manifest SHA256 detects corrupted payloads, not an independently signed release.
Obtain the ZIP from the trusted conversation. No automatic update feed exists.
For future versions, download the new updater ZIP and double-click again.

Choice 1 updates client only. New relay features require choice 2 as well.
Choice 3 restores the most recent local backup. It does NOT undo an already
successful/partial remote Cloudflare deployment, or revert node_modules.
If deployment fails, stop and retain the backup and error message; do not send
credentials or OAuth data in screenshots. A repeat update is safe for keys.
Backups are kept in .update-backups and never automatically deleted.

Verified on Linux: package hashes, apply/backup/rollback, preserving fixture
credentials and connection settings, wrong-folder rejection, JS syntax.
Windows folder picker and real Wrangler deployment still require owner test.
No paid plan upgrade, VM creation, or VM wake action is implemented.
