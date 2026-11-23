# Anima HTTPS 生圖工作中繼

外部使用者 → Cloudflare Worker → SQLite Durable Object 任務佇列。
VM 透過正常 HTTPS 443 主動拉取生圖任務 → 本機 Anima FastAPI → 將 PNG 上傳回中繼。

這是固定格式的圖片工作流程，不是通用 TCP／SSH／任意 URL 代理。任務中不能指定URL、shell指令或工具。
所有外部HTTPS均使用平台既有代理與CA；實際Worker網址若遭拒絕就停止，不繞過政策。
普通Cloudflare管理API目前能到達並回400 Missing Authorization；這不保證尚未部署的workers.dev端點可用。

## 免費與資源界線

使用者已確認現有帳號是Workers Free。只使用Free支援的SQLite型Durable Object，不使用R2、KV、付費Queue或升級API。
官方文件說明Free超額會失敗，沒有Paid方案的超額計價；帳號必須維持Free。不同帳號／日後重新部署須重新確認。
本程式不聲稱可查詢整個帳號剩餘免費額度。每日UTC最多20個生圖任務、同時1個RUNNING、最多2個未完成、單圖2MiB、任務24小時過期，於下一個請求時清理資料（沒有精確實體刪除時間保障）。
Agent預設10秒輪詢，不設固定運作或單張生成時間上限；網路請求保留逾時。新版以進度心跳續租，失聯租約到期後不自動重做任務。
圖片、prompt會傳至使用者自己的Cloudflare帳號；Cloudflare處理TLS及持久資料，請勿提交敏感內容。

來源：https://developers.cloudflare.com/durable-objects/platform/pricing/
已讀取的官方文字在docs/durable-objects-pricing.txt；不要把此app上限當成整個帳號用量保證。

## 公開部署前需要的最小授權

1. 在Cloudflare Dashboard確認**所提供Account ID的Workers方案是Free**，且已可使用workers.dev子網域；不購買網域、不升級。
2. Account ID可在帳號Overview找到，不是密碼。
3. 在 https://dash.cloudflare.com/profile/api-tokens 建立限定該Account的API Token：
   - Account → Workers Scripts → Edit（腳本、SQLite DO migration與Secrets）。
   - Account → Account Settings → Read（Wrangler讀取帳號／workers.dev設定）。
   - 不需要Global API Key、不需要Cloudflare密碼、無需DNS／KV／R2編輯權限。遇到403先核對具體所需權限，不自動擴大scope。
4. 只在本Cloud Task的Environment Secrets設定 `CLOUDFLARE_API_TOKEN`，另設定 `CLOUDFLARE_ACCOUNT_ID`。**不要貼Token到對話**。
5. 確認後執行：

```bash
cd /workspace/anima-server
CLOUDFLARE_FREE_PLAN_CONFIRMED=true .venv/bin/python relay/deploy.py
```

本次工作區已保存使用者的Free確認於私有.state；zip不包含該確認、金鑰或Token，其他環境需重新確認。
腳本會驗證Token、檢查Worker名稱是否已被占用，拒絕覆蓋不屬本專案的Worker；只有在新部署成功後才建立本專案marker。
部署後建立兩個不同的應用Secret CLIENT_KEY、AGENT_KEY。Cloudflare管理Token不會放進Worker或傳給推理程序。
透過真實HTTPS驗證認證後health=200及錯誤key=401，才保存公開URL；只有deploy命令成功不算API驗收成功。
首次部署若帳號尚無workers.dev子網域或平台拒絕該端點，會明確BLOCKED，不假造連結。

## 連接VM

部署成功後，URL位於 `.state/relay-public-url.txt`，Agent金鑰位於 `.state/relay-agent.key`。應用金鑰在 `.state/relay-keys.json`，不要提交Git。

```bash
export ANIMA_RELAY_URL='使用已實測的部署網址'
export ANIMA_RELAY_AGENT_KEY_FILE='/workspace/anima-server/.state/relay-agent.key'
.venv/bin/python relay/agent.py
```

API本機服務需先由scripts/start.sh啟動。Agent有checkpoint與本機Idempotency-Key，可在仍有效的lease內恢復並重送同一個結果，避免重做圖片。
資料與key在VM本地仍不保證跨VM保存。服務失效或lease過期須明確重送新任務；不冒充永久主機。

## 外部呼叫

取得自己CLIENT_KEY並放入客戶端受保護檔案後：

```bash
.venv/bin/python scripts/client.py --url '已驗證的Worker網址' --key-file '/path/to/client.key' --prompt 'anime mountain lake at sunrise' --output result.png
```

API為POST /v1/generations → 202／status_url → GET狀態 → GET image_url下載PNG。
CLIENT_KEY不能claim／upload；AGENT_KEY不能讀使用者API。Lease token不會回傳給使用者。

## 本機測試

```bash
cd relay
npm ci --ignore-scripts
npm test
node dev.mjs
```

Miniflare/workerd執行真實SQLite Durable Object程式，本機模擬不代表已部署到Cloudflare。
端到端測試會連接真正Anima模型；它的紀錄需與fixture測試分開閱讀。dev.mjs僅監聽127.0.0.1:8787，15分鐘自動停止。
所有測試秘密在.state，程式zip排除node_modules、模型、資料庫與秘密。

## 資源快照

Agent主動上送固定白名單系統數值；Consumer可用GET /v1/system（CLIENT_KEY）查CPU、RAM、磁碟與模型狀態。
含sampled_at、snapshot_received_at、snapshot_age_seconds與agent_recent；舊快照不等於即時資源或VM仍在線。
不接受任意環境欄位，不提供VM建立／喚醒命令。這些端點已在本機真實量測及Miniflare驗證，公開端點仍待部署授權。
