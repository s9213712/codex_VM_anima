#!/usr/bin/env bash
# 在「全新的」Ubuntu 22.04/24.04 VM 上重建 Anima 執行環境
# 用法：
#   sudo RELAY_URL=https://anima.s92137123.workers.dev \
#        AGENT_KEY_FILE=/home/ubuntu/agent.key \
#        CHECKPOINT_FILE=/home/ubuntu/models/anima-base-v1.0.safetensors \
#        bash bootstrap.sh
#
# 需要的檔案（先放好）：
#   /home/ubuntu/anima/agent.py        （repo 的 vm/agent.py）
#   /home/ubuntu/anima/workflow.json   （deploy/rebuild/workflow.template.json 修改後）
#   /home/ubuntu/agent.key             （chmod 600）
#   checkpoint 檔（沒有就先用 huggingface-cli 下載）
set -euo pipefail

RELAY_URL="${RELAY_URL:?需要 RELAY_URL}"
AGENT_KEY_FILE="${AGENT_KEY_FILE:-/home/ubuntu/agent.key}"
CHECKPOINT_FILE="${CHECKPOINT_FILE:-}"
COMFY_DIR="${COMFY_DIR:-/home/ubuntu/ComfyUI}"
VENV_DIR="${VENV_DIR:-/home/ubuntu/venvs/comfy}"
AGENT_DIR="${AGENT_DIR:-/home/ubuntu/anima}"
USER_NAME="${SUDO_USER:-ubuntu}"

as_user() { sudo -u "$USER_NAME" "$@"; }

echo "== 1. 系統套件 =="
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip git ffmpeg libgl1 libglib2.0-0 curl jq >/dev/null

echo "== 2. ComfyUI =="
if [ ! -d "$COMFY_DIR/.git" ]; then
  as_user git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git "$COMFY_DIR"
else
  as_user git -C "$COMFY_DIR" pull --ff-only
fi

echo "== 3. Python 環境 =="
as_user python3 -m venv "$VENV_DIR"
as_user "$VENV_DIR/bin/pip" install -q --upgrade pip wheel

if command -v nvidia-smi >/dev/null 2>&1; then
  echo "   偵測到 GPU：$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"
  as_user "$VENV_DIR/bin/pip" install -q torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu124
else
  echo "   沒有 GPU，安裝 CPU 版 torch"
  as_user "$VENV_DIR/bin/pip" install -q torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cpu
fi
as_user "$VENV_DIR/bin/pip" install -q -r "$COMFY_DIR/requirements.txt"

echo "== 4. 模型 =="
mkdir -p "$COMFY_DIR/models/checkpoints" "$COMFY_DIR/models/loras"
chown -R "$USER_NAME":"$USER_NAME" "$COMFY_DIR/models"
if [ -n "$CHECKPOINT_FILE" ] && [ -f "$CHECKPOINT_FILE" ]; then
  cp -n "$CHECKPOINT_FILE" "$COMFY_DIR/models/checkpoints/"
  echo "   已放入 $(basename "$CHECKPOINT_FILE")"
else
  echo "   ⚠ 沒有提供 checkpoint，請自行放到 $COMFY_DIR/models/checkpoints/"
fi

echo "== 5. systemd：ComfyUI =="
cat >/etc/systemd/system/comfyui.service <<UNIT
[Unit]
Description=ComfyUI
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${USER_NAME}
WorkingDirectory=${COMFY_DIR}
ExecStart=${VENV_DIR}/bin/python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

echo "== 6. systemd：Anima agent =="
chmod 600 "$AGENT_KEY_FILE" 2>/dev/null || true
cat >/etc/systemd/system/anima-agent.service <<UNIT
[Unit]
Description=Anima relay agent
After=network-online.target comfyui.service
Wants=network-online.target

[Service]
Type=simple
User=${USER_NAME}
WorkingDirectory=${AGENT_DIR}
ExecStart=/usr/bin/python3 ${AGENT_DIR}/agent.py \\
  --relay ${RELAY_URL} \\
  --key-file ${AGENT_KEY_FILE} \\
  --backend comfy \\
  --comfy-url http://127.0.0.1:8188 \\
  --workflow ${AGENT_DIR}/workflow.json \\
  --model-name ${MODEL_NAME:-anima-base-v1.0}
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now comfyui
systemctl enable --now anima-agent

echo "== 7. 等待就緒 =="
for i in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8188/system_stats >/dev/null 2>&1; then
    echo "   ComfyUI OK"
    break
  fi
  sleep 2
done

echo
echo "== 完成，請驗收 =="
systemctl is-active comfyui anima-agent
journalctl -u anima-agent -n 10 --no-pager
