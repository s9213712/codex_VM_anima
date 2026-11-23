# 用 Gemini 建出「能接這個專案」的 VM

> 先分清楚：**Gemini 有四個不同的東西**，只有一個能真的生出你要的 GPU VM。
> 純用 Jules 的雲端 VM 出圖是行不通的（無 GPU、VM 短命）。

---

## 1. 四種 Gemini，四種用途

| 表面 | 是什麼 | 能幫你做的 | 能不能當出圖後端 |
|---|---|---|---|
| **Gemini CLI**（`gemini` 指令） | 在你自己的機器上跑的 coding agent，能執行 shell | **產出並執行 `gcloud` 指令、寫 startup script、debug** | 它不提供 VM；但能幫你建 |
| **Jules**（jules.google.com） | Google 的雲端非同步 agent，每個 task 一台短命 Ubuntu VM | 改 repo、跑測試、開 PR、產生設定檔 | ❌ 無 GPU、VM 會被回收 |
| **Gemini Code Assist**（IDE 外掛） | 編輯器內的補完／聊天 | 寫程式、解釋程式碼 | ❌ |
| **Gemini API** | 模型本身 | 你要自己接工具 | ❌ |

**結論：想要一台能長期跑 ComfyUI + agent.py 的 VM，要用 Gemini CLI 幫你操作 Google Cloud（GCE），或直接用手上的機器 / Runpod。**

---

## 2. 路線 A：用 Jules 幫你把 repo 環境建好（不需要 GPU）

用途：讓 Jules 改 relay、補測試、產生部署腳本，開 PR 回來。

### 步驟

1. jules.google.com → 左側 codebases 選 `s9213712/codex_VM_anima`
2. 上方 **Configuration** → **Initial Setup** 貼：

```bash
set -e
cd anima-cloudflare
npm ci
npm run build:ui
npm test
node ../scripts/check-secrets.mjs
```

3. 按 **Run and Snapshot**（成功後每個 task 都從這個快照起，不用重裝）
4. 之後每個 task 直接給需求即可 —— repo 根目錄的 `AGENTS.md` 已寫好規則（禁區、指令、契約）

### 可以直接貼給 Jules 的任務範例

```
讀 AGENTS.md。在 anima-cloudflare 新增一個端點 GET /v1/stats，
回傳最近 24 小時的任務數、成功率、平均耗時（從 jobs 表算）。

限制：
- 不要改 Durable Object 的 instance 名稱
- 不要改動既有 relay 契約
- 要加單元測試到 test/relay.test.js
- 完成後跑 npm test 與 node ../scripts/check-secrets.mjs，貼出結果
```

---

## 3. 路線 B：真的開一台 GPU VM（GCE）

這是唯一能「接上 relay 並長期出圖」的 Gemini 路線 —— 用 Gemini CLI 幫你下 `gcloud`。

### 3.1 先讓 Gemini CLI 幫你確認前置

貼給 Gemini CLI：

```
我要在 Google Cloud 開一台 GPU VM 跑 ComfyUI，並用 systemd 常駐。
請幫我：
1. 檢查我目前的 gcloud 專案、可用區域、GPU quota（nvidia-l4 / nvidia-t4）
2. 產出建立 VM 的完整指令（Ubuntu 22.04、200GB 磁碟、開啟開機自動重啟）
3. 說明如果 quota 不足要怎麼申請
不要直接執行，先把指令給我確認。
```

常見指令（`g2-standard-4` = 1× L4 24GB，最便宜的 GPU 家族）：

```bash
gcloud compute instances create anima-gpu \
  --zone=asia-east1-b \
  --machine-type=g2-standard-4 \
  --maintenance-policy=TERMINATE --restart-on-failure \
  --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud \
  --boot-disk-size=200GB --boot-disk-type=pd-balanced \
  --metadata=install-nvidia-driver=True \
  --metadata-from-file startup-script=deploy/gpu-vm/install-comfyui.sh
```

> - 不需要開任何 inbound 防火牆：agent.py 只往外連 relay
> - SSH 用 `gcloud compute ssh anima-gpu --zone=asia-east1-b --tunnel-through-iap`
> - GCE GPU 需要先有 quota（`GPUS_ALL_REGIONS`），新帳號通常是 0，要申請
> - 費用：L4 約 US$0.70/hr（含磁碟），**不用時一定要 stop**

### 3.2 安裝（腳本已放在 repo）

```bash
# VM 內
sudo bash install-comfyui.sh        # 裝 ComfyUI + systemd，聽 127.0.0.1:8188
```

腳本會：裝系統套件 → 檢查 `nvidia-smi` → clone ComfyUI → 建 venv（torch cu124）
→ 寫 `comfyui.service` → 開機自啟 → 等到 `/system_stats` 有回應。

### 3.3 放模型與 workflow

```bash
mkdir -p ~/ComfyUI/models/checkpoints
# 放你的 anima-base-v1.0.safetensors（或其他 checkpoint）

mkdir -p ~/anima && cd ~/anima
# 複製 repo 的 vm/agent.py
# 匯出 ComfyUI 的 API 格式 workflow 成 workflow.json（節點要含 {{prompt}} 等佔位符）
```

### 3.4 接上 relay

```bash
sudo cp anima-agent.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now anima-agent

journalctl -u anima-agent -n 20 --no-pager
curl -s -H "Authorization: Bearer $CLIENT_KEY" \
  https://anima.s92137123.workers.dev/healthz | python3 -m json.tool
```

期望：log 出現 `[agent] connected ...`，`/healthz` 的 `agent_recent` 為 `true`。

### 3.5 可以貼給 Gemini CLI 的除錯提示詞

```
這台 VM 的 anima-agent.service 沒有出現在 relay 的 healthz（agent_recent=false）。
請依序檢查並回報：
1. systemctl status anima-agent 與 journalctl -u anima-agent -n 50
2. 金鑰檔案權限與內容長度（不要印出金鑰本身）
3. curl -s -o /dev/null -w "%{http_code}" https://anima.s92137123.workers.dev/healthz
4. curl -s http://127.0.0.1:8188/system_stats | head -c 200
只回報診斷結果與修法，不要改 relay 端。
```

---

## 4. 差不多功能的現成專案（可直接參考或改用）

| 專案 | 用途 | 對你的價值 |
|---|---|---|
| [`runpod-workers/worker-comfyui`](https://github.com/runpod-workers/worker-comfyui) | 官方 ComfyUI serverless worker | 不想養 VM 時，直接當 GPU 後端；需一層轉接器接到 relay |
| [`karaposu/comfyui-on-cloud`](https://github.com/karaposu/comfyui-on-cloud) | GCE 上裝 ComfyUI + 開機自動啟動 | 和路線 B 的 `install-comfyui.sh` 幾乎同一件事，可對照 |
| [`jandolina/RunPodComfyUI`](https://github.com/jandolina/RunPodComfyUI) | Runpod + `CF_TUNNEL_TOKEN` 自動開 Cloudflare tunnel | 想用 push 模式（bridge）時的現成樣板 |
| [`Dijeo/comfyui-api-proxy`](https://github.com/Dijeo/comfyui-api-proxy) | FastAPI 代理，加驗證與簡化 API | 我們的 `bridge/comfy_bridge.py` 是同類但更小 |
| [`HAMM3REXTREME/ComfyUI-Installer`](https://github.com/HAMM3REXTREME/ComfyUI-Installer) | Linux 一鍵安裝 + systemd | 另一種安裝腳本寫法可參考 |
| [`Betakontext/cloudflared-quicktunnel-bridge`](https://github.com/Betakontext/cloudflared-quicktunnel-bridge) | 發布 trycloudflare 臨時網址 | 只做短期 demo 時可用 |

---

## 5. 三條路的取捨

| 你的情況 | 建議 |
|---|---|
| 只想改程式、不想花錢 | **Jules**（路線 A），環境免費、有快照 |
| 想長期出圖、有自己的顯卡 | 本機跑 `agent.py`（見 `docs/VM-SETUP.md`），**不建議 GCE** |
| 沒有顯卡、要長期出圖 | GCE L4（路線 B）或 Runpod；記得關機省錢 |
| 只要偶爾出幾張 | Runpod serverless（按秒計費），不需常駐 |

⚠️ 不管你選哪條，**relay 端都不需要改**：agent.py 是 outbound 連線，
VM 不需要公網 IP、不需要開 port。

---

## 6. 驗收清單

```bash
# VM 內
systemctl is-active comfyui anima-agent          # 兩個都要 active
curl -s http://127.0.0.1:8188/system_stats | head -c 80
journalctl -u anima-agent -n 5 --no-pager | grep connected

# 你的電腦（有 client.key）
curl -s -H "Authorization: Bearer $CLIENT_KEY" \
  https://anima.s92137123.workers.dev/healthz | python3 -m json.tool
curl -s -X POST https://anima.s92137123.workers.dev/v1/generations \
  -H "Authorization: Bearer $CLIENT_KEY" -H "Content-Type: application/json" \
  -d '{"prompt":"test","width":128,"height":128,"steps":1,"seed":1}'
```

最後一項回 202 且帶 `id`，代表整條鏈路（Gemini 建的 VM → relay → 出圖）接通。
