# Anima Cloudflare Relay — 接手文件

更新：2026-11-23　狀態：**線上運作中**

## 一、這是什麼

Windows 端到「Cloudflare Worker 中繼」再到「Codex VM 代理」的**單一用途圖片任務 relay**。

```
Windows 客戶端 (Python)
   │  HTTPS + Bearer CLIENT_KEY
   ▼
Cloudflare Worker「anima」(workers.dev)
   │  Durable Object「AnimaRelay」+ SQLite
   │  Bearer AGENT_KEY
   ▼
Codex VM 代理（輪詢 /agent/claim）
   └ 生成 PNG → /agent/jobs/<id>/complete
```

設計上是**刻意窄化**的：只接受固定欄位的 job（prompt/negative_prompt/width/height/steps/seed），
明確拒絕未知欄位，避免變成任意 URL／命令轉發器。

## 二、線上實測（2026-11-23）

```
GET /healthz   → {"relay":"READY","agent_recent":true,
                  "agent":{"ready":true,"busy":false,"model":"Anima CPU", ...}}
錯誤 key       → 401
```

VM 回報的資源：
- CPU：5 可見核 / 4 配額核，使用率 81%
- 記憶體：16 GB 上限，已用 6.7 GB
- 磁碟：33.7 GB，已用 7.9 GB

`agent_recent: true` 代表代理在 60 秒內有心跳 → **整條鏈是活的**。

## 三、檔案地圖

```
D:\anima-cloudflare-windows\
├─ anima-cloudflare\                 部署包（雲端端 + 客戶端）
│  ├─ src\worker.js                  151 行，全部後端邏輯
│  ├─ wrangler.jsonc                 Worker "anima"、DO "AnimaRelay"、account d3a507ba…
│  ├─ Deploy-Anima.ps1               65 行，互動式部署
│  ├─ package.json                   test 腳本指向 test/*.test.js（目前不存在）
│  ├─ .private\                      ★ 金鑰（絕不外傳）
│  │  ├─ client.key                  44 B
│  │  ├─ agent.key                   44 B
│  │  ├─ relay-keys.json
│  │  └─ relay-url.txt               https://anima.s92137123.workers.dev
│  ├─ anima-client\                  Python 客戶端（標準庫，無 torch）
│  │  ├─ anima_client.py             103 行，API + 存圖
│  │  ├─ cloud_task.py               60 行，Codex CLI 探測（唯讀）
│  │  ├─ github_transport.py         115 行
│  │  ├─ dashboard.py / .html        85 行
│  │  ├─ connection.json             backend/api/key_file/codex_environment_id
│  │  └─ installed-version.json      2026.11.23-turbo8
│  ├─ vm-pairing\                    VM 配對（pair-vm.cjs、Pair-VM.ps1、加密 json、公鑰）
│  └─ .update-backups\2026-11-23T14-02-23-565Z
└─ anima-easy-updater\               更新器（manifest + payload + update.cjs）
   ├─ manifest.json                  turbo8 的檔案 SHA256
   └─ payload\{client,relay}\        來源包
```

## 四、後端行為（worker.js 摘要）

| 端點 | 認證 | 行為 |
|---|---|---|
| `GET /` | 無 | 服務說明 |
| `GET /healthz` | CLIENT_KEY | relay + agent 心跳 |
| `GET /v1/system` | CLIENT_KEY | VM 資源快照（safeMetrics 白名單） |
| `POST /v1/generations` | CLIENT_KEY | 建 job；佇列上限 2、每日 20（UTC） |
| `GET /v1/jobs/<id>` | CLIENT_KEY | 狀態 + 進度 |
| `GET /v1/jobs/<id>/image` | CLIENT_KEY | PNG（成功才給） |
| `POST /agent/claim` | AGENT_KEY | 取 job，發 lease 35 分鐘 |
| `POST /agent/heartbeat` | AGENT_KEY | 心跳 |
| `POST /agent/jobs/<id>/progress` | AGENT_KEY + X-Lease-Token | 進度（stage/step/elapsed） |
| `POST /agent/jobs/<id>/complete` | AGENT_KEY + X-Lease-Token | PNG 上傳（≤2 MB，驗 magic + sha256） |
| `POST /agent/jobs/<id>/fail` | AGENT_KEY + X-Lease-Token | 失敗原因 |

安全機制：
- Bearer 以 SHA-256 + 常數時間比較
- 請求 body 有大小上限（job 8 KB、progress 12 KB、圖片 2 MB）
- 未知欄位直接 422（防變成通用轉發）
- lease 過期自動標 FAILED；expired RUNNING 每次請求時清理
- 圖片重送若 sha256 相同 → 冪等回應

## 五、目前缺口與風險

| # | 問題 | 影響 | 建議 |
|---|---|---|---|
| 1 | **`npm test` 沒有測試檔**（`test/*.test.js` 不存在，跑出 pass 0） | 改 worker.js 無回歸保護 | 補 miniflare 測試：驗證認證、欄位驗證、lease、配額 |
| 2 | **整個專案沒有 git** | 無法回溯，改壞難救 | `git init` + `.gitignore` 排除 `.private/`、`node_modules/`、`.wrangler/`、`*.key` |
| 3 | 金鑰以明文放 `.private/` | 本機洩漏風險 | 保持不入 git；考慮 DPAPI/憑證管理 |
| 4 | `observability.enabled = false` | 出事沒日誌 | 開啟 Workers Logs（免費額度內） |
| 5 | `connection.json` 的 `key_file` 是相對路徑 `../.private/client.key` | 換工作目錄就找不到 | 改成相對 connection.json 解析，或存絕對路徑 |
| 6 | 每日 20 次、併發 2 次是硬編碼 | 要調整需改碼重部署 | 移到 `wrangler.jsonc` vars |
| 7 | 圖片 BLOB 存 DO SQLite（≤2 MB/張） | 大量使用會吃 DO 儲存費 | 監控；必要時改 R2 |
| 8 | 代理是 **Anima CPU** | 生成慢（CPU 推理） | 若要快，得讓 VM 用 GPU 或改推理路徑 |
| 9 | 沒有 CI | 部署靠手動 PowerShell | 至少加一個 `npm test` + `wrangler deploy --dry-run` 的檢查腳本 |

## 六、接手後的建議順序

1. **建立 git**（排除 secrets）→ 之後所有改動可回溯
2. **補測試**（先把現有行為鎖住，再改功能）
3. **開 observability** + 寫一個 `health.sh` 一鍵檢查
4. 把配額/併發改成環境變數
5. 修 `key_file` 路徑解析
6. 再談功能（例如 R2、多模型、儀表板強化）

## 七、常用指令

```bash
cd D:\anima-cloudflare-windows\anima-cloudflare

# 健康檢查（不印金鑰）
K=$(tr -d '\r\n' < .private/client.key); U=$(tr -d '\r\n' < .private/relay-url.txt)
curl -s -H "Authorization: Bearer $K" "$U/healthz"

# 部署（會開瀏覽器 OAuth）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Deploy-Anima.ps1

# 乾跑檢查
npx wrangler deploy --dry-run

# 測試（目前 0 個）
npm test
```

## 七點五、部署副本（RPi5）

```
s92137@192.168.18.34:~/anima-cloudflare-windows/
  ├─ anima-cloudflare/（含 .private/，權限 700/600）
  ├─ anima-easy-updater/
  └─ README.md / HANDOVER.md
```

- 2026-11-24 由 Windows 端以 tar + scp 複製，金鑰依使用者指示一併帶過去
- 已在 Pi 5 上實測 `curl /healthz` 成功（relay READY、agent_recent=true）
- ⚠️ `agent.key` 在 Pi 上等於「可領取任務」的權限；若不再需要，刪掉該檔即可

## 八、不可外傳

`.private/*.key`、`.wrangler/`、`vm-pairing/vm-pairing.encrypted.json`、OAuth 憑證
（`C:\Users\user\AppData\Roaming\xdg.config\.wrangler\config\default.toml`）。
截圖前務必遮蔽。
