#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[[ -f .state/model-path.txt ]] || { echo 'BLOCKED: verified model snapshot is missing'; exit 2; }
mkdir -p .state .outputs
chmod 700 .state .outputs
.venv/bin/python - <<'CODE'
from pathlib import Path
import secrets
p=Path('.state/api.key')
if not p.exists():p.write_text(secrets.token_urlsafe(32));p.chmod(0o600)
if len(p.read_text().strip())<32:raise RuntimeError('API key too short')
CODE
exec flock --nonblock .state/api.lock timeout --signal=TERM --kill-after=15 10800 .venv/bin/uvicorn anima_api.app:app --host 127.0.0.1 --port 8765 --workers 1
