#!/usr/bin/env bash
# 在「現有的」VM 上執行，把重建所需的一切收集成一個 JSON（不會含金鑰內容）
# 用法：bash collect.sh > vm-manifest.json
set -uo pipefail

say() { printf '%s\n' "$*" >&2; }

json_escape() { python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'; }

section() { printf '\n===== %s =====\n' "$*" >&2; }

say "收集系統資訊…"
KERNEL=$(uname -srm)
CPU=$(nproc 2>/dev/null || echo 0)
MEM=$(awk '/MemTotal/{printf "%.1f", $2/1024/1024}' /proc/meminfo 2>/dev/null || echo 0)
DISK=$(df -h / 2>/dev/null | awk 'NR==2{print $2" total, "$4" free"}')

GPU="none"
if command -v nvidia-smi >/dev/null 2>&1; then
  GPU=$(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader | head -1)
fi

section "ComfyUI"
COMFY_DIR="${COMFY_DIR:-$HOME/ComfyUI}"
COMFY_VERSION="not found"
[ -d "$COMFY_DIR/.git" ] && COMFY_VERSION=$(git -C "$COMFY_DIR" rev-parse --short HEAD 2>/dev/null)

CHECKPOINTS=""
if [ -d "$COMFY_DIR/models/checkpoints" ]; then
  CHECKPOINTS=$(cd "$COMFY_DIR/models/checkpoints" && ls -1S 2>/dev/null | head -20)
fi
LORAS=""
if [ -d "$COMFY_DIR/models/loras" ]; then
  LORAS=$(cd "$COMFY_DIR/models/loras" && ls -1S 2>/dev/null | head -20)
fi
CUSTOM_NODES=""
if [ -d "$COMFY_DIR/custom_nodes" ]; then
  CUSTOM_NODES=$(cd "$COMFY_DIR/custom_nodes" && ls -1 2>/dev/null | head -30)
fi

PIP_FREEZE=""
for v in "$HOME/venvs/comfy" "$COMFY_DIR/venv" "$HOME/ComfyUI/venv"; do
  if [ -x "$v/bin/pip" ]; then
    PIP_FREEZE=$("$v/bin/pip" freeze 2>/dev/null | grep -Ei '^(torch|torchvision|torchaudio|numpy|safetensors|transformers|diffusers|comfyui)' | head -30)
    break
  fi
done

section "systemd"
UNIT_COMFY=$(systemctl cat comfyui.service 2>/dev/null || echo "not installed")
UNIT_AGENT=$(systemctl cat anima-agent.service 2>/dev/null || echo "not installed")
# 移除可能的金鑰內容
UNIT_AGENT=$(printf '%s' "$UNIT_AGENT" | sed -E 's/(KEY|TOKEN|PASSWORD)=.*/\1=[REDACTED]/I')

section "agent 行程"
AGENT_CMD=$(ps -eo args 2>/dev/null | grep -m1 '[a]gent\.py' || echo "not running")
AGENT_DIR=""
case "$AGENT_CMD" in
  *agent.py*) AGENT_DIR=$(printf '%s' "$AGENT_CMD" | grep -oE '/[^ ]+/agent\.py' | head -1 | xargs -r dirname) ;;
esac
WORKFLOW=""
[ -n "$AGENT_DIR" ] && WORKFLOW=$(ls -1 "$AGENT_DIR"/*.json 2>/dev/null | head -5)
WORKFLOW_NAMES=$(printf '%s' "$WORKFLOW" | tr '\n' ' ')

section "輸出 JSON"
cat <<JSON
{
  "collected_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "hostname": "$(hostname)",
  "kernel": "$KERNEL",
  "cpu_cores": $CPU,
  "memory_gib": $MEM,
  "disk": "$DISK",
  "gpu": "$GPU",
  "comfy": {
    "dir": "$COMFY_DIR",
    "git_short": "$COMFY_VERSION",
    "checkpoints": $(printf '%s' "$CHECKPOINTS" | json_escape),
    "loras": $(printf '%s' "$LORAS" | json_escape),
    "custom_nodes": $(printf '%s' "$CUSTOM_NODES" | json_escape)
  },
  "python": $(printf '%s' "$PIP_FREEZE" | json_escape),
  "systemd": {
    "comfyui": $(printf '%s' "$UNIT_COMFY" | json_escape),
    "anima_agent": $(printf '%s' "$UNIT_AGENT" | json_escape)
  },
  "agent": {
    "process": $(printf '%s' "$AGENT_CMD" | json_escape),
    "dir": "$AGENT_DIR",
    "workflows": $(printf '%s' "$WORKFLOW_NAMES" | json_escape)
  }
}
JSON
