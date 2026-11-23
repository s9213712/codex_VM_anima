#!/usr/bin/env bash
# 在 Ubuntu 22.04/24.04 + NVIDIA GPU 的 VM 上安裝 ComfyUI 並註冊 systemd
# 用法：sudo bash install-comfyui.sh
# 完成後 ComfyUI 會聽在 127.0.0.1:8188（只綁本機，不對外開 port）
set -euo pipefail

USER_NAME="${SUDO_USER:-ubuntu}"
HOME_DIR="/home/${USER_NAME}"
COMFY_DIR="${HOME_DIR}/ComfyUI"
VENV_DIR="${HOME_DIR}/venvs/comfy"

echo "== 1. 系統套件 =="
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip git ffmpeg libgl1 libglib2.0-0 curl >/dev/null

echo "== 2. NVIDIA 驅動檢查 =="
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "找不到 nvidia-smi。請先安裝 GPU 驅動（GCE 可用 --install-nvidia-driver=latest）" >&2
  exit 1
fi
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

echo "== 3. 取得 ComfyUI =="
if [ ! -d "${COMFY_DIR}/.git" ]; then
  sudo -u "${USER_NAME}" git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git "${COMFY_DIR}"
else
  sudo -u "${USER_NAME}" git -C "${COMFY_DIR}" pull --ff-only
fi

echo "== 4. Python 環境 =="
sudo -u "${USER_NAME}" python3 -m venv "${VENV_DIR}"
sudo -u "${USER_NAME}" "${VENV_DIR}/bin/pip" install -q --upgrade pip wheel
sudo -u "${USER_NAME}" "${VENV_DIR}/bin/pip" install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
sudo -u "${USER_NAME}" "${VENV_DIR}/bin/pip" install -q -r "${COMFY_DIR}/requirements.txt"

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

systemctl daemon-reload
systemctl enable --now comfyui

echo "== 6. 等待 ComfyUI 就緒 =="
for i in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8188/system_stats >/dev/null 2>&1; then
    echo "ComfyUI OK"
    break
  fi
  sleep 2
done

echo
echo "完成。檢查："
echo "  systemctl status comfyui --no-pager"
echo "  curl -s http://127.0.0.1:8188/system_stats | head -c 200"
echo
echo "下一步：把 agent.py 與 workflow.json 放到 ${HOME_DIR}/anima/，"
echo "再安裝 anima-agent.service（見 deploy/gpu-vm/anima-agent.service）"
