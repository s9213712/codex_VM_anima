#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
MODE="${1:-named}"
[[ "$MODE" == named || "$MODE" == quick ]] || { echo 'Usage: tunnel.sh named|quick'; exit 2; }
if [[ "$MODE" == named ]]; then
 [[ -n "${TUNNEL_TOKEN_FILE:-}" && -r "$TUNNEL_TOKEN_FILE" ]] || { echo 'BLOCKED: mount the Named Tunnel token as a secret file and set TUNNEL_TOKEN_FILE; do not paste it into chat'; exit 2; }
 exec timeout --signal=TERM --kill-after=10 10800 .tools/cloudflared tunnel --no-autoupdate --protocol http2 run --token-file "$TUNNEL_TOKEN_FILE"
fi
# Run only after the platform permits Quick Tunnel API and edge connections.
exec timeout --signal=TERM --kill-after=10 10800 .tools/cloudflared tunnel --no-autoupdate --protocol http2 --url http://127.0.0.1:8765 --ha-connections 1
