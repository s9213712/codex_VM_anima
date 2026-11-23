# 在 Codex VM 建置並連結 relay

> 目標：讓 Codex VM 裡的 ComfyUI 接上 `https://anima.s92137123.workers.dev`，
> 收到 relay 派的任務、生成圖片、回傳 PNG。
> **VM 只需要對外連線，不需要開任何 inbound port。**

---

## 0. 先看懂架構

```
手機 / 瀏覽器
     │  HTTPS + client.key
     ▼
Cloudflare Worker（relay，Durable Object 保管任務）
     ▲
     │  HTTPS + agent.key（VM 主動往外連，每 10 秒心跳、每 2 秒領任務）
     │
Codex VM ── agent.py ──► ComfyUI 127.0.0.1:8188
```

三支金鑰，用途不同，**不要混用**：

| 金鑰 | 檔案 | 誰用 | 能做什麼 |
|---|---|---|---|
| `CLIENT_KEY` | `.private/client.key` | 瀏覽器 / 你的腳本 | 送單、查任務、抓圖 |
| `AGENT_KEY` | `.private/agent.key` | VM 的 agent | 心跳、領任務、回報進度與結果 |
（本 relay 只有這兩支金鑰，沒有 admin key。）

把 `agent.key` 給 VM，等於讓 VM 能「領走任務」；`client.key` 給 VM 沒有意義。

---

## 1. 前置條件（VM 上）

```bash
python3 --version        # 3.8 以上，標準庫即可，不需 pip 安裝任何套件
curl -s http://127.0.0.1:8188/system_stats | head -c 80   # ComfyUI 活著
```

若 ComfyUI 不在 8188，記下實際位址（例如 `http://127.0.0.1:8189`）。

---

## 2. 把金鑰放進 VM（三選一）

**A. 從 repo 讀（最省事）**
若 VM 已經 clone 了 `codex_VM_anima`，金鑰不在 repo 裡（已 gitignore），所以要另外放。

**B. 在 Codex 的環境變數 / secret 設定裡填**（推薦）
在 Codex 的 VM 設定新增 `ANIMA_AGENT_KEY`，之後由 systemd 讀取，金鑰不落在磁碟的明文檔。

**C. 手動 scp**（若 VM 有 SSH）

```bash
scp anima-cloudflare/.private/agent.key user@vm:/home/user/anima/agent.key
chmod 600 /home/user/anima/agent.key
```

> 不論哪種方式，**權限一律 `chmod 600`**，且不要 commit、不要貼進聊天。

---

## 3. 放置檔案

```
/home/user/anima/
├── agent.py        # 來自 repo：anima-cloudflare/vm/agent.py
├── workflow.json   # ComfyUI 的 API 格式 workflow（見第 4 節）
└── agent.key       # chmod 600
```

`workflow.json` 必須是 **ComfyUI API 格式**（`Save (API Format)` 匯出的那種），
而且裡面要含這幾個佔位符字串，agent 會做字串替換：

| 佔位符 | 會被換成 |
|---|---|
| `{{prompt}}` | 正向提示詞 |
| `{{negative}}` | 負面提示詞 |
| `{{width}}` / `{{height}}` | 寬 / 高（整數） |
| `{{steps}}` | 步數 |
| `{{seed}}` | 種子 |

例：CLIPTextEncode 的 `text` 寫 `"{{prompt}}"`，EmptyLatentImage 的 `width` 寫 `"{{width}}"`。

---

## 4. 先手動跑一次（除錯用）

```bash
cd /home/user/anima
python3 agent.py \
  --relay https://anima.s92137123.workers.dev \
  --key-file ./agent.key \
  --backend comfy \
  --comfy-url http://127.0.0.1:8188 \
  --workflow ./workflow.json \
  --model-name anima-base-v1.0
```

成功的話會看到：

```
[agent] connected to https://anima.s92137123.workers.dev backend=comfy host=... Linux-...
```

另一個終端機驗證（用 client.key，不是 agent.key）：

```bash
K=$(cat client.key)
curl -s -H "Authorization: Bearer $K" \
  https://anima.s92137123.workers.dev/healthz \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print("agent_recent",d["agent_recent"],"age",d["agent_age_seconds"],"model",d["agent"]["system"]["model"]["state"])'
```

期望：`agent_recent True age <10 model READY`

再送一張最小測試（128×128、1 步，很快）：

```bash
curl -s -X POST https://anima.s92137123.workers.dev/v1/generations \
  -H "Authorization: Bearer $K" -H "Content-Type: application/json" \
  -d '{"prompt":"test","width":128,"height":128,"steps":1,"seed":1}'
```

拿到 `id` 後：

```bash
curl -s -H "Authorization: Bearer $K" \
  https://anima.s92137123.workers.dev/v1/jobs/<id> | python3 -m json.tool
curl -s -H "Authorization: Bearer $K" \
  https://anima.s92137123.workers.dev/v1/jobs/<id>/image -o out.png
file out.png     # 應顯示 PNG image data
```

---

## 5. 設成常駐（systemd）

`/etc/systemd/system/anima-agent.service`：

```ini
[Unit]
Description=Anima relay agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=user
WorkingDirectory=/home/user/anima
Environment=ANIMA_AGENT_KEY_FILE=/home/user/anima/agent.key
ExecStart=/usr/bin/python3 /home/user/anima/agent.py \
  --relay https://anima.s92137123.workers.dev \
  --key-file /home/user/anima/agent.key \
  --backend comfy \
  --comfy-url http://127.0.0.1:8188 \
  --workflow /home/user/anima/workflow.json \
  --model-name anima-base-v1.0
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now anima-agent
sudo systemctl status anima-agent --no-pager
journalctl -u anima-agent -f      # 看即時 log
```

重開機後應自動恢復；`Restart=always` 讓它掛掉 5 秒後自己起來。

---

## 6. agent 呼叫的 relay 端點（給要自己實作的人）

| 動作 | 方法 / 路徑 | 必要標頭 | 說明 |
|---|---|---|---|
| 心跳 | `POST /agent/heartbeat` | `Authorization: Bearer <agent.key>` | 每 10 秒一次，讓 relay 知道 VM 還活著 |
| 領任務 | `POST /agent/claim` | 同上 | 有任務會回 `{job:{id,lease,request}}`，沒有回空 |
| 回報進度 | `POST /agent/jobs/{id}/progress` | 同上 + `X-Lease-Token` | `{stage,step,elapsed_seconds}` |
| 交件 | `POST /agent/jobs/{id}/complete` | 同上 + `X-Lease-Token` + `X-Generation-Metadata` | body 是 PNG 原始 bytes |
| 失敗 | `POST /agent/jobs/{id}/fail` | 同上 + `X-Lease-Token` | `{error:"..."}` |

租約（lease）預設 **15 分鐘**；超過就視為失敗，任務會標 FAILED。

---

## 7. 常見錯誤對照

| 現象 | 原因 | 解法 |
|---|---|---|
| `401 unauthorized` | 用了 `client.key` 當 agent，或金鑰有換行/空白 | 改用 `agent.key`，`tr -d '\r\n'` 清乾淨 |
| `/healthz` 的 `agent_recent:false` | agent 沒跑、或心跳送不出去 | `journalctl -u anima-agent -n 50` |
| `422` 尺寸錯誤 | 寬高必須 128–1024 且為 32 的倍數 | 用 UI 的預設值；1080 不合法，改 1088（靠 workflow 放大） |
| 任務卡 `RUNNING` 直到 15 分鐘逾時 | ComfyUI 掛掉 / workflow 節點錯誤 | 手動 `curl 127.0.0.1:8188/system_stats`，看 journal |
| `ComfyUI finished without an image output` | workflow 沒有 SaveImage，或存到非 output 目錄 | 確認 workflow 末端是 `SaveImage` |
| 收到 `503 Agent offline` | VM 超過 5 分鐘沒心跳 | 重啟 service；或設定 `FALLBACK_URL` 走備援 |
| 圖抓到但 0 bytes | 用了舊的 job id（24 小時後清除 / 換過 DO 實例） | 重新送單 |

---

## 8. 整段貼給 Codex 的提示詞

```
這台 VM 要接上既有的 Cloudflare relay（不要改 relay 端）。

1. 建立 /home/user/anima，放入 repo 的 anima-cloudflare/vm/agent.py
   （只依賴 Python 標準庫，不要引入第三方套件）。
2. 金鑰從環境變數 ANIMA_AGENT_KEY 或 /home/user/anima/agent.key（chmod 600）讀取，
   不要寫進任何 commit。
3. 確認 ComfyUI 位址（預設 http://127.0.0.1:8188），並把現有 workflow 匯出成
   API 格式放到 /home/user/anima/workflow.json，節點中要含
   {{prompt}} {{negative}} {{width}} {{height}} {{steps}} {{seed}} 佔位符。
4. 建立 systemd unit anima-agent.service（Restart=always, RestartSec=5, WantedBy=multi-user.target），
   執行參數：
   --relay https://anima.s92137123.workers.dev --key-file /home/user/anima/agent.key
   --backend comfy --comfy-url http://127.0.0.1:8188 --workflow /home/user/anima/workflow.json
5. 啟用並開機自啟，然後驗證：
   - journalctl -u anima-agent 出現 "[agent] connected ..."
   - curl relay /healthz 的 agent_recent 為 true 且 agent_age_seconds < 10
   - 送一張 128x128 steps=1 的測試，GET /v1/jobs/<id>/image 得到合法 PNG
6. 把驗證結果（含 PNG 尺寸）回報，失敗要貼出 journalctl 最後 50 行。
```
