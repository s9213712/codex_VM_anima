# VM 建置、配對與恢復教程

## 1. 需求與費用界線

目前實測是 Linux x86_64、4 核 CPU 配額、16GiB RAM，沒有 GPU。需要 Python3.12、uv、Git、curl、flock、OpenSSL，可存取 Hugging Face、Civitai、Python/npm 官方來源與自己的 Cloudflare Worker。首次下載需足夠磁碟，至少預留 8GiB；實際全部依賴與快取需要更多。

本機推理不呼叫付費模型 API，但 Codex 工作、排程與工具操作仍受方案額度和環境生命週期限制；沒有官方餘額 API，不能查剩餘 Codex 額度。方案用完或平台停止 VM 後，無法保證繼續執行。

沒有透過背景循環、排程或 Tunnel 保證 VM 永久在線，也不會自動租用付費主機。

## 2. 取得程式

在 VM 終端：

```bash
cd /workspace
git clone --branch work/anima-restore https://github.com/s9213712/codex_VM_anima.git anima-server
cd /workspace/anima-server
```

若工作區已存在，先 `git status`，不要覆蓋未知修改。已建立 origin 的乾淨 checkout 可用 `git pull --ff-only origin work/anima-restore` 更新來源。**更新來源不等於熱更新既有模型程序**，不要在生成中重啟。

## 3. 安裝與模型核對

確認工具存在，安裝 uv 若未提供可依 https://docs.astral.sh/uv/getting-started/installation/ 官方方式，在使用者可寫目錄安裝。

```bash
python3 --version
uv --version
openssl version
bash scripts/install.sh
```

安裝程式以 uv.lock 固定依賴，Torch/Torchvision 使用官方 CPU index；下載固定 revision 的 Diffusers Anima 並核對 safetensors 的 LFS SHA256。Turbo v0.2 由使用者指定 Civitai 模型頁，固定 file/version ID 與完整 SHA256；不執行模型 remote code，不載入 pickle 模型。

`.cache`、`.venv` 與 `.state` 不提交 Git。模型下載/安裝需要網路，推理 worker 使用 offline 模式。相同環境重跑安裝保留既有模型及金鑰，並核對完整性。

## 4. 啟動 API

```bash
bash scripts/start.sh
```

這會保持前景運作，僅綁 `127.0.0.1:8765`，`flock` 防止第二份模型。另開終端檢查：

```bash
curl --fail http://127.0.0.1:8765/healthz
```

API 回應是開發檢查資料，正常使用者看 Windows 介面的中文欄位。`ready=true`、Turbo 已載入後才能接單。模型載入時間視 CPU、磁碟而定；不是 HTTP200 就一定 ready。

初始化產生 `.state/api.key`（0600），請勿輸出或傳送它。模型工作程序限制 RSS12GiB。沒有單張生成固定逾時；平台可停止 VM，資源不足或模型錯誤仍會失敗。

## 5. 產生此 VM 專用配對工具

Windows 首次 Cloudflare 部署成功後，從那次部署取得自己的實際 URL。在 VM：

```bash
.venv/bin/python scripts/prepare-pairing.py --url https://你的實際Worker.workers.dev
```

命令產生 `.state/vm-pairing.zip`，包含公鑰與 Windows 加密工具；私鑰始終留在 `.state/pairing-private.pem`。**公鑰工具可下載，私鑰不可下載或提交 Git。**

把公鑰 ZIP 下載到 Windows，解壓縮後放成：

```text
D:\AnimaApp\
  .private\agent.key
  vm-pairing\pair-vm.cjs
  vm-pairing\vm-public.pem
```

在 Windows PowerShell：

```powershell
cd D:\AnimaApp\vm-pairing
node .\pair-vm.cjs
```

只傳回產生的 `vm-pairing.encrypted.json`。這是 RSA-OAEP-SHA256 加密資料，不是明文金鑰；仍建議只傳給對應工作，勿用它當公開更新檔。

VM 取得附件後，將附件放入受保護的 `.state`，執行：

```bash
.venv/bin/python scripts/accept-pairing.py --file .state/vm-pairing.encrypted.json
```

程式核對格式、公鑰指紋、密文長度與解密結果，再保存 agent key 和 Worker URL；不顯示明文。解密成功不是遠端連線成功，下一節才驗證接單。

## 6. 啟動接單 Agent

API 須繼續運作，另開 VM 終端：

```bash
cd /workspace/anima-server
export ANIMA_RELAY_URL="$(cat .state/relay-public-url.txt)"
export ANIMA_RELAY_AGENT_KEY_FILE="$PWD/.state/relay-agent.key"
.venv/bin/python relay/agent.py
```

URL不是密碼；金鑰用檔案路徑傳遞，不放指令參數。保留平台原有 proxy/CA，不禁用 TLS 驗證。正常 Agent 主動走 HTTPS443，Cloudflare 不需主動連 VM。

在 Windows 介面按更新資源，檢查快照時間與模型狀態。送一張 256×256、8步圖片，確認經 Cloudflare 生成、回傳並下載後，才算你的完整路徑驗收。

Agent 不設預設運作時限，但不是平台的常駐服務承諾。`--seconds` 可選擇明確限定測試程序；網路請求仍有逾時，活躍任務透過進度續租。失聯任務不會永久卡住。

## 7. 暫停、程序停止與重建

- **Agent停止，API正常**：確認沒有第二份 Agent，使用上一節命令重啟。仍有效且已保存 checkpoint 的工作可嘗試接續；過期任務不能偷偷重做。
- **API停止**：先查任務。重啟 API 會把本機未完成工作明確標失敗，不保證從中間 latent 繼續。
- **VM暫停**：回 Codex 工作要求恢復，等待平台提供環境。Cloudflare、GitHub 或 Windows 客戶端沒有這台 VM 的開機 API。
- **VM重建**：從 Git clone、重裝依賴/模型、重新配對。舊私鑰與資料庫若遺失，不能靠 Git 恢復它們。
- **額度不足**：不能承諾 VM 還可用；改用自己的合適主機需自行安排。程式可搬移，但不自動啟用付費資源。

不要在任務正在生成時套用會停止程序的更新。只更新前台與 Worker 歷史介面通常不需要重啟模型。

## 8. 排錯

| 狀況 | 檢查 |
|---|---|
| Turbo LoRA missing/hash mismatch | 執行 `scripts/install-turbo.py`；未核對成功不會假標 Turbo |
| 模型 ERROR | 看 `.state/worker.log`，勿把整個含私人資料的目錄公開 |
| RELAY_ERROR HTTP401 | 核對 Windows `.private` 與 VM agent key 是否同一組配對 |
| HTTP404/403 | URL或平台網路政策可能不符；不繞過明確拒絕 |
| Queue full/20-task cap | 先人工檢查既有任務和產物；不要刪除 DB 或繞過限制 |
| 資源快照舊 | 快照不代表當前 VM在線，先查 API/Agent 程序 |

## 9. 測試與更新提交

```bash
.venv/bin/python -m pytest -q
(cd relay && npm test)
node --test updater/update.test.cjs
python scripts/build-updater.py
git diff --check
git status
```

只提交來源、測試、文件與刻意提供的無私人資訊測試範例；不要執行 `git add -f .state`。更新器 payload 必須與來源同步。工作分支為 `work/anima-restore`，不自動合併 main。
