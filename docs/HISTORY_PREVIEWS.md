# History and previews

Cloudflare GET /v1/jobs uses existing authenticated CLIENT_KEY, returns up to 50 retained jobs, newest first. No lease, agent credential, raw logs or image blob appears in the list. Existing 24-hour retention remains unchanged. This requires owner deployment through the updater; no migration or VM restart is needed.

Client /api/history requires the same localhost Host, Origin and session protections as other APIs. Historical prompts are rendered with textContent. There are 12 cards/page, status filtering, prompt/ID search, parameter reuse without resubmission and lazy PNG previews (maximum three simultaneous downloads). History refreshes every 30 seconds and after submission/completion. Viewing an old result never auto-downloads it; the download link remains available.

The client stores metadata in per-endpoint SQLite under history-data, keeps up to 1000 records and displays the newest 200. At the cap, live cloud jobs remain visible with an archive warning; existing records are not deleted. Up to 100MiB of PNGs are cached only when viewed, with SHA256 validation against known metadata. Once full, new previews can still stream but are not retained. No automatic image deletion. Cached files and metadata persist through client restarts and the updater; they are not a cloud backup.

An expired cloud image cannot be recovered unless this computer already cached/downloaded it. Offline/expired metadata is labeled local snapshot, not live state. Cloudflare history cannot expose VM-only diagnostic test generations that were never submitted through Cloudflare. Existing retained cloud orders become visible after update, even if created before this version.

Validation: 21 Python tests, 8 Miniflare tests, JS syntax and updater payload integrity/rollback tests. Tests cover offline cached previews, restart persistence, endpoint isolation, chronological sorting, authentication, wrong-path rejection, SHA256 mismatch and exclusion of lease/image blobs from cloud history. Windows and public Cloudflare rollout remain owner actions; no existing running inference was restarted for this feature.
