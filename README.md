# Anima Cloudflare Relay

把「Windows 客戶端 → Cloudflare Worker 中繼 → VM 影像代理」串起來的單一用途圖片生成服務。

- 客戶端不需要 GPU，只要有瀏覽器或 Python
- VM 只需**對外**連線（HTTPS），不必開任何 inbound port
- Cloudflare 端保存工作佇列、進度、結果圖（Durable Object + SQLite）
- 附一個網頁 UI（`/ui`），不用再看原始 JSON

```
Windows / 瀏覽器
   │  HTTPS + Bearer CLIENT_KEY
   ▼
Cloudflare Worker「anima」+ Durable Object「AnimaRelayV2」
   │  Bearer AGENT_KEY（VM 主動輪詢）
   ▼
VM 代理（agent.py）→ ComfyUI / 自訂命令 → PNG 回傳
```

---

## 目錄

| 路徑 | 說明 |
|---|---|
| `anima-cloudflare/src/worker.js` | 後端全部邏輯（Worker + Durable Object） |
| `anima-cloudflare/src/ui.html` | 網頁 UI（`/ui`） |
| `anima-cloudflare/vm/agent.py` | **VM 代理參考實作**（只用標準庫） |
| `anima-cloudflare/test/relay.test.js` | 單元測試（`npm test`） |
| `anima-cloudflare/scripts/health.mjs` | 健康檢查（`npm run health`） |
| `anima-cloudflare/anima-client/` | Python 客戶端（可選） |
| `anima-cloudflare/vm-pairing/` | 金鑰配對工具（RSA-OAEP 加密後才上傳） |
| `anima-easy-updater/` | 既有安裝的更新器 |

---

## 1. 前置需求

| 項目 | 版本 |
|---|---|
| Node.js | 22+（部署與測試） |
| Cloudflare 帳號 | Workers Free 即可 |
| Python | 3.10+（客戶端與 VM 代理） |
| VM | 任何能跑 ComfyUI 的 Linux/Windows；不需要公開 IP |

---

## 2. 部署 Cloudflare 端

```powershell
cd anima-cloudflare
npm install
powershell -NoProfile -ExecutionPolicy Bypass -File .\Deploy-Anima.ps1
```

腳本會依序：`wrangler login`（瀏覽器授權）→ 部署 Worker 與 Durable Object → 建立 `CLIENT_KEY` / `AGENT_KEY` 兩個 secret → 驗證 `healthz=200`、錯誤金鑰 `=401`。

部署後：

```powershell
# 金鑰在 .private\（千萬不要上傳到 Git 或聊天）
type .private\client.key
type .private\agent.key
type .private\relay-url.txt
```

> 重新部署不會輪換金鑰；刪掉 `.private\` 會讓所有既有客戶端與代理斷線。

### 手動部署（不用腳本）

```bash
npx wrangler deploy
npx wrangler secret put CLIENT_KEY
npx wrangler secret put AGENT_KEY
```

---

## 3. 使用網頁 UI

打開 `https://<你的-worker>.workers.dev/ui`，貼上 **relay 網址**與 **client.key**，之後會存在該瀏覽器（localStorage）。

UI 提供：

- 系統狀態：Relay、VM 是否在線（幾秒前心跳）、模型狀態、佇列、CPU/記憶體、最近錯誤
- 產生表單：提示詞、負面提示詞、尺寸（256/512/768/1024 或自訂）、步數、種子（可隨機）
- 任務列表：狀態標籤、去噪進度條、耗時、錯誤訊息、完成後直接顯示圖片

尺寸限制：**128–1024 且必須是 32 的倍數**（`512`、`640`、`768`、`1024` 都合法；`500` 會在前端就被擋下）。

### 手機／其他裝置帶入金鑰

1. 在電腦上產生一次性 QR（會把 client key 放進網址的 `#` 片段，不會送到伺服器）：

   ```bash
   cd D:/anima-cloudflare-windows
   K=$(tr -d '

' < anima-cloudflare/.private/client.key)
   npx --yes qrcode -o pair-qr.png -w 640 "https://<worker>.workers.dev/ui#key=$K"
   ```

2. 用該裝置掃 `pair-qr.png` → 開啟後會自動填入並儲存，網址列上的金鑰會被立刻清除
3. `pair-qr.png` 已列入 `.gitignore`，**不要上傳**

> QR 內含金鑰，用完請刪除圖片；若懷疑外流，請輪換 `CLIENT_KEY`（同時更新 VM 端設定）。

---

## 4. 設定 VM 代理（給 Codex 的提示詞）

把下面整段貼給 Codex（在同一個有 VM 的對話裡），並把 `<RELAY_URL>` 換成你的 workers.dev 網址。

```text
你是這台 VM 上的 Anima 影像代理。請完成安裝並常駐執行，過程中不要印出任何金鑰內容。

1. 確認環境：python3 --version（需 3.10+）、curl 可用；若要用 ComfyUI，確認 http://127.0.0.1:8188 有回應。
2. 建立目錄 /opt/anima，把 agent.py 放進去（來源：本 repo 的 anima-cloudflare/vm/agent.py）。
3. 取得金鑰：relay 網址 <RELAY_URL>，agent key 由我提供的配對檔解密取得；
   金鑰只寫入 /opt/anima/agent.key（chmod 600），不要 echo、不要貼到對話。
4. 啟動（ComfyUI 後端）：
   python3 /opt/anima/agent.py --relay <RELAY_URL> --key-file /opt/anima/agent.key \
       --backend comfy --comfy-url http://127.0.0.1:8188 --workflow /opt/anima/workflow.json
   若沒有 ComfyUI，改用 --backend command --command "<你的生成指令，輸出到 $ANIMA_OUT>"。
5. 用 systemd 或 nohup 常駐，並設定開機自動啟動：
   systemd 服務名 anima-agent.service，Restart=always，EnvironmentFile=/opt/anima/env。
6. 驗證：日誌要看到 [agent] connected；relay 的 /healthz 回報 agent_recent=true。
7. 代理行為：每 10 秒送 heartbeat（ready/busy/system），輪詢 /agent/claim；
   拿到工作後依序回報 ENCODING → DENOISING → DECODING → SAVING，
   最後把 PNG 以 /agent/jobs/<id>/complete 上傳（帶 X-Lease-Token）。
8. 限制：只允許對外 HTTPS，不要開 inbound port；不要修改 relay 上的其他資料。
```

### ComfyUI workflow 佔位符

`workflow.json` 是 ComfyUI 的 **API 格式** workflow（非 UI 存檔）。代理會替換這些字串：

| 佔位符 | 來源 |
|---|---|
| `{{prompt}}` | 使用者提示詞 |
| `{{negative}}` | 負面提示詞 |
| `{{width}}` / `{{height}}` | 尺寸 |
| `{{steps}}` | 步數 |
| `{{seed}}` | 種子 |

### 換模型 / LoRA

- **換模型**：改 `workflow.json` 裡 `CheckpointLoaderSimple` 的 `ckpt_name`（例如 SDXL 需同時改解析度與 sampler 節點）
- **加 LoRA**：在 workflow 插入 `LoraLoader`（`lora_name`、`strength_model`、`strength_clip`），或直接用包含 LoRA 的 checkpoint
- **指定模型**：`--model-name "Anima-2B"` 只影響 UI 顯示；實際模型由 workflow 決定

### 常見的 systemd 單元

```ini
[Unit]
Description=Anima VM agent
After=network-online.target

[Service]
WorkingDirectory=/opt/anima
EnvironmentFile=/opt/anima/env
ExecStart=/usr/bin/python3 /opt/anima/agent.py --relay ${RELAY_URL} --key-file /opt/anima/agent.key --backend comfy --comfy-url http://127.0.0.1:8188 --workflow /opt/anima/workflow.json
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## 5. API

所有請求都需要 `Authorization: Bearer <key>`（`/agent/*` 用 `AGENT_KEY`，其餘用 `CLIENT_KEY`）。

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/healthz` | relay 狀態、代理心跳年齡、佇列、最近錯誤、策略 |
| GET | `/v1/system` | VM 資源快照 |
| POST | `/v1/generations` | 建立任務，回 202 |
| GET | `/v1/jobs/{id}` | 任務狀態與進度 |
| GET | `/v1/jobs/{id}/image` | 結果 PNG |
| POST | `/agent/claim` | 代理取任務（發 lease） |
| POST | `/agent/heartbeat` | 代理心跳 |
| POST | `/agent/jobs/{id}/progress` | 進度（需 `X-Lease-Token`） |
| POST | `/agent/jobs/{id}/complete` | 上傳 PNG（≤2 MB，驗 PNG magic + sha256） |
| POST | `/agent/jobs/{id}/fail` | 回報失敗 |

建立任務：

```bash
curl -s -X POST "$RELAY/v1/generations" \
  -H "Authorization: Bearer $CLIENT_KEY" -H "Content-Type: application/json" \
  -d '{"prompt":"a cat","width":512,"height":512,"steps":8,"seed":42}'
```

欄位只接受 `prompt`、`negative_prompt`、`width`、`height`、`steps`、`seed`；**多帶任何欄位會回 422**（避免 relay 變成任意轉發器）。

---

## 6. 行為與限制

| 項目 | 值 |
|---|---|
| 同時任務 | 2 |
| 每日上限 | 20（UTC 換日） |
| 代理離線 | 90 秒內仍收單（標記等待）；超過 5 分鐘直接 503 |
| 卡住的任務 | PENDING 超過 10 分鐘 → FAILED |
| 租約 | 15 分鐘，過期自動 FAILED |
| 圖片 | ≤ 2 MB、必須是 PNG |

---

## 6.5 Fallback（VM 離線時改用其他後端）

當 VM 代理心跳超過 **5 分鐘**沒更新，relay 會把新任務轉給 fallback 後端；VM 在線時永遠優先走 VM。

### 啟用

```bash
npx wrangler secret put FALLBACK_URL    # 例：https://anima-bridge.example.com
npx wrangler secret put FALLBACK_KEY    # 與 bridge 的 BRIDGE_TOKEN 相同
```

> 注意：Worker/Durable Object 的行為變更要 bump `src/worker.js` 裡的 `RELAY_INSTANCE` 版本號再部署，
> 否則既有 DO 實例仍跑舊程式碼。

### Fallback 契約（任何後端只要實作這個就能接）

```
POST {FALLBACK_URL}/generate
Authorization: Bearer {FALLBACK_KEY}
{"prompt","negative_prompt","width","height","steps","seed"}
→ 200 image/png（≤2 MB）
GET {FALLBACK_URL}/healthz → {"ok":true}
```

### 三種後端

| 後端 | 做法 |
|---|---|
| **本地 ComfyUI** | 在跑 ComfyUI 的機器上執行 `python3 bridge/comfy_bridge.py --port 8899 --workflow workflow.json`，再用 `cloudflared tunnel --url http://127.0.0.1:8899` 取得 HTTPS 網址 |
| **Colab** | 同一個 bridge 腳本貼進 notebook，配合 cloudflared/ngrok；記得 Colab 會逾時斷線 |
| **ComfyUI Cloud / 其他 API** | 寫一個小轉接器（把對方 API 包成上面的 `/generate` 契約），或用 `--backend command` 的 agent 當轉接 |

### 行為

- 只有在 `agent_age > 300s` 時才會走 fallback；90–300 秒仍是排隊等 VM
- fallback 任務在 UI 上會標「備援」，`/v1/jobs/{id}` 的 `backend` 欄位為 `fallback`
- fallback 失敗會直接把任務標 FAILED，不會無限重試

### 大圖（1920×1088）怎麼做

Relay 驗證上限是 **1024 / 32 的倍數**（1080 不是 32 的倍數，最近合法值是 1088）。
要 1080p 成品，請在 **VM 的 workflow 末端加放大節點**，不要放寬 relay：

```json
"9":  {"class_type": "ImageScale", "inputs": {"image": ["8", 0], "upscale_method": "lanczos", "width": 1920, "height": 1088, "crop": "disabled"}},
"10": {"class_type": "SaveImage",  "inputs": {"images": ["9", 0], "filename_prefix": "anima"}}
```

或品質優先：`UpscaleModelLoader`（RealESRGAN_x4plus）+ `ImageUpscaleWithModel` + `ImageScale`。
CPU 上 512² 生成約 1–2 分，放大到 1920×1088 約再加 20–40 秒，遠比直接生 2 MP 安全。

### 歷史任務回 404

兩個原因，屬正常行為：

1. **保留 24 小時**：`DELETE FROM jobs WHERE created < now-86400000`
2. **更換 Durable Object 實例**（`RELAY_INSTANCE` 版本號變更）會換到新的 SQLite 儲存，舊紀錄消失

UI 會把完成圖快取在瀏覽器 IndexedDB，伺服器清掉後仍顯示「已過期」並可下載；
不同裝置的快取各自獨立。

### 觀測

`wrangler.jsonc` 已開啟 `observability`（取樣 20%），可在 Cloudflare Dashboard → Workers → anima → Logs 查詢。

---

## 7. 疑難排解

| 症狀 | 原因與處理 |
|---|---|
| `503 Agent offline` | VM 代理沒在跑或心跳中斷。到 VM 上 `systemctl status anima-agent` |
| `agent_recent:false` | 同上；`/healthz` 會顯示 `agent_age_seconds` |
| 任務一直 PENDING | 代理在忙或沒取單；10 分鐘後會自動 FAILED，不會永遠卡住 |
| `401` | 金鑰錯（`client.key` vs `agent.key` 用錯） |
| `429` | 佇列已滿（2）或今日已 20 次 |
| `422 Unknown job field` | 多送了欄位，只送六個允許的欄位 |
| 改了 `worker.js` 但行為沒變 | **Durable Object 會固定在舊版本程式碼**。把 `src/worker.js` 裡的 `RELAY_INSTANCE` 名稱加一版（例如 `...-v3`）再部署，會建立新實例（舊任務紀錄會消失） |
| `/ui` 回 401 | 部署剛完成，等幾秒再試；確認 `wrangler.jsonc` 有 `"rules": [{"type":"Text","globs":["**/*.html"]}]` |

---

## 8. 安全

- `CLIENT_KEY` / `AGENT_KEY` 只在 Cloudflare secret 與本機 `.private\`；**不要進 Git、不要貼截圖**
- `vm-pairing/vm-pairing.encrypted.json` 才可上傳，`.private\` 與 `agent.key` 絕對不行
- 圖片存在 Durable Object SQLite，24 小時後任務紀錄自動清除
- 客戶端只允許 HTTPS；`http://127.0.0.1` 僅在 `allow_local` 測試時可用

---

## 9. 開發

```bash
cd anima-cloudflare
npm test          # 12 個單元測試
npm run health    # 檢查線上 relay（不印金鑰）
npm run check     # 測試 + wrangler dry-run
npx wrangler deploy
```

---

## 10. 後續規劃

- [ ] Fallback：VM 離線時轉送 ComfyUI Cloud / Colab / 本地 ComfyUI（介面已預留）
- [ ] UI：任務歷史、圖片下載、批次佇列
- [ ] 模型選擇：SDXL / 指定 checkpoint / LoRA 參數
- [ ] 批次任務與排程
- [ ] Workers Logs（observability）

---

## License

Private project. 權重與模型授權依各自來源（Anima / SDXL 等）為準。
