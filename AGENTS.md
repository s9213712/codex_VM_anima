# AGENTS.md

給雲端 coding agent（Codex Cloud、Jules 等）看的專案說明。Claude Code 請讀 `CLAUDE.md`。

## 這是什麼

Anima 出圖服務：Cloudflare Worker（relay）+ Durable Object（任務佇列）+
外部 GPU 機器上的 `agent.py`（驅動 ComfyUI）。前端是 Worker 內嵌的 `/ui`。

```
anima-cloudflare/           # relay（Worker + Durable Object）
  src/worker.js             # fetch 路由 + DO 類別（必須保留 export default 在此檔）
  src/logic.js              # 純邏輯，可被 node --test 直接 import
  src/ui.html               # 前端（會被 build:ui 內嵌）
  src/ui.generated.js       # 自動產生，勿手改
  test/relay.test.js        # 單元測試
  scripts/build-ui.mjs      # ui.html -> ui.generated.js（正規化為 LF）
  scripts/health.mjs        # 線上健康檢查
  vm/agent.py               # GPU 端代理（純標準庫）
  bridge/comfy_bridge.py    # fallback 用的 HTTP bridge
anima-easy-updater/         # 本機更新器（manifest + payload + rebuild-payload.mjs）
scripts/check-secrets.mjs   # 阻止金鑰進 git
docs/                       # VM-SETUP / CLOUD-AGENTS / CODEX-TASKS
```

## 指令

```bash
cd anima-cloudflare
npm ci
npm run build:ui      # 改過 src/ui.html 一定要跑
npm test              # 15 項
node --check src/worker.js src/logic.js
```

線上健康檢查（需要金鑰，通常不要跑）：

```bash
node scripts/health.mjs
```

## 規則（違反會壞事）

1. **不要動 `anima-cloudflare/.private/`**：裡面是 `client.key` / `agent.key`，已在 `.gitignore`。
2. **不要把金鑰寫進任何檔案或 commit**；`node scripts/check-secrets.mjs` 必須通過。
3. **`export default` 必須留在 `src/worker.js`**：搬去 `logic.js` 會讓整個 Worker 404。
4. **改 `src/ui.html` 後一定要 `npm run build:ui`** 並把 `src/ui.generated.js` 一起 commit，否則線上不會更新。
5. **Durable Object 的程式碼會被釘在建立時的版本**：改 DO 內部邏輯要 bump
   `src/worker.js` 裡的 `single-approved-image-worker-v4` 版本號，而且**會清空既有任務紀錄**——
   這件事要先問 owner，不要自己決定。
6. **relay 契約不要改**：`POST /v1/generations`、`GET /v1/jobs/{id}`、`GET /v1/jobs/{id}/image`、
   `POST /agent/{claim,heartbeat}`、`POST /agent/jobs/{id}/{progress,complete,fail}`。
   客戶端（`anima-client/`）與 VM agent 都依賴它。
7. **尺寸限制**：寬高 128–1024 且為 32 的倍數。1080 不合法（最近值 1088），大圖靠 workflow 放大，不要放寬驗證。
8. **不要 commit `node_modules`、`.wrangler`、`pair-qr.png`**。

## 這個環境做不到的事

- 沒有 GPU：不要嘗試在這裡跑 ComfyUI 生成圖片
- VM 生命週期短：不要在這裡常駐 `vm/agent.py`，relay 的租約是 15 分鐘
- 不要在雲端 VM 執行 `wrangler deploy`（會動到正式服務），除非 owner 明確要求
