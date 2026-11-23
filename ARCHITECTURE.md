# Architecture

The default path is Windows stdlib Python UI → Cloudflare Worker/SQLite Durable Object → outbound polling agent → localhost FastAPI → isolated CPU Diffusers worker. GitHub publishes source and updater payload, not an online VM or private job queue in the default mode.

The API's SQLite queue and .state checkpoints are local development state. Cloudflare stores externally retained jobs, progress, and PNGs; Windows SQLite caches selected history per endpoint. This does not provide infinite retention or cross-VM shared memory.

Model subprocess reports real scheduler completion and captures per-job stdout/stderr. Agent forwards bounded progress/log tails with lease authentication. The browser uses human-readable summaries, authenticated PNG fetches and snapshot charts; it does not fabricate progress or present stale data as current.

The Windows source checkout stays separate from the installed app. Update-From-Git fetches the approved branch with fast-forward only and runs the newly fetched installer payload. Existing installation credentials/config/history are excluded from replacement. Stored OAuth is reused; noninteractive failure stops without starting a new login.
