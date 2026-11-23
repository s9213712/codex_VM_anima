#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v gh >/dev/null || { echo 'Install GitHub CLI from https://cli.github.com/'; exit 2; }
gh auth status --hostname github.com >/dev/null 2>&1 || gh auth login --hostname github.com --git-protocol https --web --scopes repo
exec python3 dashboard.py
