# Anima CPU API — 恢復版

真實 CPU BF16 Diffusers 生圖 API。模型固定 `circlestone-labs/Anima-Base-v1.0-Diffusers`，revision `073c3a9db359c31ad0e8aa268d15775473c2176c`。
個人非商業模型服務測試，無租用GPU或付費API。不可把本專案當24小時永久VPS。

```bash
./scripts/install.sh
./scripts/start.sh
```

Python3.12／uv／curl／flock，Debian x86_64。Torch及Torchvision只用官方CPU index；依賴由uv.lock鎖定。
模型使用safetensors並驗證官方LFS SHA256；不啟用模型remote code。
API在127.0.0.1:8765，只有一個worker；SQLite任務可跨程序保存，但VM重建後本地資料不保證保留。
首次啟動建立.state/api.key（0600）；不顯示、不提交。重複啟動由flock擋下，不會誤啟第二個大型模型。

```bash
.venv/bin/python scripts/client.py --prompt 'anime scenery, a red cabin beside a mountain lake, sunrise' --output example.png
```

- GET /healthz：真實就緒狀態與模型程序RSS觀測。
- POST /v1/generations：需Bearer；202回任務id與status_url。
- GET /v1/jobs/{uuid}：需Bearer，PENDING／RUNNING／SUCCEEDED／FAILED。
- GET /v1/jobs/{uuid}/image：需Bearer，成功後下載PNG。
- /docs：OpenAPI。不能以URL query傳key。

CPU4執行緒，預設256×256、8steps，尺寸128–512且32倍數，steps1–20。單張600秒、worker 12GiB RSS、佇列容量2、每個DB最多20次任務。
API及Tunnel最長3小時；模型loading超過180秒停止。服務重啟會將中斷任務明確標失敗，需使用者重新送出。
外部API採非同步202避免CPU推理期間佔用長HTTP請求。金鑰與原始資料請放適當秘密儲存；免費不等於公開端點無濫用風險。

## Cloudflare 開通

[完整管理員申請清單](docs/NETWORK_OPENING_REQUEST.md)。本機程式存在不代表已公開。
目前沒有Named Tunnel Secret、公開portal或新增網路許可。Quick Tunnel API先前回403；沒有繞過封鎖。

網路許可及帳號既有hostname準備好後，將token以秘密檔掛載並設定TUNNEL_TOKEN_FILE，再執行：

```bash
./scripts/tunnel.sh named
```

只有平台允許Quick Tunnel API及edge連線後，才使用 `./scripts/tunnel.sh quick`。
不要貼Token到對話，不需DuckDNS，不購買網域或啟用付費方案。

## 測試及持久保存

`.venv/bin/pytest -q` 驗證API、參數、佇列、重啟；它不載入模型，不能替代真實生圖測試。
當次實際API生成結果記錄在docs/evidence；歷史結果不會冒充此次實測。
原始碼zip排除模型cache、SQLite、token及API key；請另存使用者指定的外部儲存，否則仍可能在VM重建後遺失。

## HTTPS 圖片工作中繼

已新增 [relay/README.md](relay/README.md)：外部HTTP提交 → Cloudflare Worker／SQLite DO → VM主動拉取 → 真實Anima生成 → PNG上傳／下載。
固定圖片schema、不同角色金鑰、lease、每日20任務、重送去重。它使用普通HTTPS443，沒有通用TCP／命令轉送。
本機Miniflare與真實Anima的端到端測試已成功；公開Worker尚未部署，仍需Cloudflare Account ID與最小權限Token以Environment Secrets提供。
使用者已確認Workers Free，不啟用付費功能。實際workers.dev端點的可達性仍須公開部署後驗證。
