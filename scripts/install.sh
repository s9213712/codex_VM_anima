#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p .state .cache .tools docs/evidence
chmod 700 .state
export UV_CACHE_DIR="$ROOT/.cache/uv"
uv sync --frozen
curl --fail --silent --show-error --location --max-time 30 'https://huggingface.co/api/models/circlestone-labs/Anima-Base-v1.0-Diffusers/revision/073c3a9db359c31ad0e8aa268d15775473c2176c?blobs=true' -o docs/evidence/model-info.json
.venv/bin/python scripts/download.py
.venv/bin/python scripts/install-turbo.py
HASH=97bb3b02d23a5980fc9c15a1a270e692da1923f103f920d5b16d4931d5ab55e7
if [[ ! -x .tools/cloudflared ]] || ! printf '%s  .tools/cloudflared\n' "$HASH" | sha256sum -c --status; then
 curl --fail --silent --show-error --location --max-time 120 https://github.com/cloudflare/cloudflared/releases/download/2026.11.1/cloudflared-linux-amd64 -o .tools/cloudflared.partial
 printf '%s  .tools/cloudflared.partial\n' "$HASH" | sha256sum -c -
 chmod 755 .tools/cloudflared.partial
 mv .tools/cloudflared.partial .tools/cloudflared
fi
