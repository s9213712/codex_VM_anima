# Windows 完整教程

## 1. 分清三個位置

- **Windows 原始碼**：建議 `D:\AnimaSource`，從 GitHub clone；只用於取得更新，不放金鑰。
- **Windows 應用程式**：你目前的 `D:\anima-cloudflare-windows\anima-cloudflare`，或首次安裝用 `D:\AnimaApp`；包含 `.private`、`anima-client`、Cloudflare 設定與歷史。
- **雲端 VM**：例如 `/workspace/anima-server`，真正載入模型及推理的 Linux 電腦。Windows UI 及 Cloudflare 不是生圖主機。

不要把應用程式放進 Git checkout，避免金鑰或執行資料混入原始碼。更新器會拒絕相同或內嵌位置。

## 2. 安裝工具

用各官方網站安裝，安裝後關閉並重新開啟 PowerShell：

| 工具 | 版本/用途 | 官方來源 |
|---|---|---|
| Git | 拉取程式 | https://git-scm.com/download/win |
| GitHub CLI（選用） | 日後私人儲存庫的一次性登入 | https://cli.github.com/ |
| Node.js | 22 或以上；Wrangler、更新器 | https://nodejs.org/ |
| Python | 客戶端 3.10+，不需要 Torch | https://www.python.org/downloads/ |

Python 安裝時可選 Add Python to PATH。PowerShell 中檢查：

```powershell
git --version
node --version
py -3 --version
```

如果 `py` 沒有安裝，使用 `python --version`；啟動器會嘗試這兩種方式。Windows 不需要下載 Anima 模型或安裝 CUDA。

## 3. 已有應用程式：一次性改用 Git

第一次在 PowerShell 執行（公開 repo 不需要 GitHub 登入）：

```powershell
git clone --branch work/anima-restore https://github.com/s9213712/codex_VM_anima.git D:\AnimaSource
```

如果日後改為私人 repo，可用官方 gh 在自己的瀏覽器完成一次登入及 `gh auth setup-git`；不要在聊天貼 Token。例行更新不會重跑登入。

現在雙擊 `D:\AnimaSource\Update-From-Git.bat`：

1. 先關閉舊 Anima 客戶端視窗，不要停止 VM。
2. 初次會開資料夾選擇器，選你原本含 `.private` 的應用程式根目錄，**不是 `anima-client` 子目錄，也不是原始碼目錄**。
3. 程式自動選擇前台與 Cloudflare 更新，不再要求填一般選項。
4. 沿用你先前核准的帳號與 `anima` Worker；沒有新增服務或變更方案。請自行讓帳號維持 Workers Free。
5. 只使用既有 Cloudflare OAuth，不開登入、不輪替金鑰、不重填 Account ID 或 URL。憑證過期/撤銷時會停止，不能保證永遠免重新登入。
6. 等待 `PASS: Cloudflare health=200; wrong key=401` 與 `DONE`。
7. 雙擊原應用程式下的 `anima-client\start-windows.bat`。

以後不再下載更新 ZIP，直接雙擊同一個 `Update-From-Git.bat` 即可。第一次成功後安裝路徑會保存在使用者的 LocalAppData/AnimaUpdater；若找不到舊路徑會重新詢問。

## 4. 全新安裝 Cloudflare 中繼

已有可用部署的人跳過此節，避免在新資料夾誤產生不同金鑰。

1. 完成上一節的工具與 clone。
2. 把 `D:\AnimaSource\windows-relay` **整個複製**到 `D:\AnimaApp`。之後所有 runtime 設定都改在 `D:\AnimaApp`，不要改原始碼 checkout。
3. 開啟 Cloudflare 控制台，確認目標帳號是 Workers Free。未有 workers.dev 子網域時先設定，不購買網域、不升級。
4. 到 Workers & Pages 檢查有無同名 `anima` Worker。若是自己的 Hello World 測試 Worker，可授權取代；若是重要既有服務，先停下，不要覆蓋。
5. 在 PowerShell 執行：

```powershell
cd D:\AnimaApp
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Deploy-Anima.ps1
```

`Bypass` 只作用於這次 PowerShell 程序，不永久變更執行政策。

6. 輸入 `FREE`，貼上正確帳號的 **Account ID**（32 位十六進位字元，不是 Token）。可從控制台網址 `https://dash.cloudflare.com/<Account-ID>/...` 或帳號詳細資料複製。
7. 瀏覽器開啟時核對 Cloudflare 官方網址及帳號；檢查 OAuth 權限，授權後回終端。
8. whoami 顯示正確帳號後，輸入 `anima`，同意更新該 Worker。
9. 程式部署 `AnimaRelay` SQLite Durable Object migration 及 `RELAY` 繫結，產生獨立 CLIENT_KEY/AGENT_KEY。
10. 最後貼 **部署輸出中的實際 Worker URL**，不是 `anima.yourname.workers.dev` 範例。
11. 確認健康檢查成功。不成功時保留 `.private`，不要刪除重試。
12. 執行 `D:\AnimaSource\Update-From-Git.bat`，選 `D:\AnimaApp`，完成第一次客戶端安裝。

本專案擁有者目前 Worker URL 為 `https://anima.s92137123.workers.dev`。其他帳號不可照抄，必須使用自己的實際部署網址。

## 5. 配對 VM

初次部署成功只代表中繼可用，不代表 VM 已連接。依 [VM 教程](VM_GUIDE.md) 由 VM 產生專用配對公鑰及工具，放入應用程式的 `vm-pairing` 目錄。從該目錄執行 `node .\pair-vm.cjs`，只把加密檔傳回指定 VM。

不要拿公開 repo 中的歷史公鑰替全新 VM 配對，除非已核對該 VM 確實保有對應私鑰。`.private/client.key` 供客戶端，`.private/agent.key` 只供 VM 接單；Cloudflare OAuth 是另外一種憑證。

## 6. 生圖操作

1. 雙擊應用程式的 `anima-client\start-windows.bat`，保持終端開啟。
2. 使用新開啟的本機網址。舊網址的 port 可能不同，不能固定收藏舊 port。
3. 確認 VM 有近期快照、模型 READY；Turbo 資訊需由 VM 實際回報。
4. 初次建議 256×256、8 步。長寬可獨立調整，須在 128–1024 及 32 的倍數。
5. 輸入提示詞。Turbo CFG 1 下負面提示詞不參與引導。
6. 送出後看中文狀態、步數、耗時與原始日誌。步數只在真實計算完成後增加；去噪 100% 後還有解碼。
7. 完成後可預覽、下載。勾選自動下載時需瀏覽器允許；關機或休眠無法繼續下載。
8. 歷史單可依狀態與提示詞搜尋；「帶回參數」只填表單，不會偷偷重送或下載。

系統資源及歷史每 30 秒讀取；進度與日誌約每 5 秒。不是即時串流。CPU 曲線使用 cgroup 配額，RAM 含快取；看不到新快照不能當 VM 還在線。

## 7. 歷史、圖片與備份

Cloudflare 任務約 24 小時到期。本機 `anima-client/history-data` 保存曾讀取的紀錄與曾開啟的圖片；不會自動恢復從未取得、已過期的圖片。詳見 [保存上限](HISTORY_PREVIEWS.md)。

更新前備份在應用程式 `.update-backups`，更新器選 3 可還原最近一次應用檔案。這不等於回復 Cloudflare 版本，也不回復 node_modules。不要把 `.private`、圖片歷史或整個應用程式目錄推到 GitHub。

## 8. iPhone 操作

Windows 客戶端的 `127.0.0.1` 指 Windows 本機，不能在 iPhone Safari 直接開啟。可以沿用你現在的遠端桌面操作 Windows。這個教程沒有部署公開免密碼 Web UI，也沒有把客戶端 port 暴露到網際網路。

用 iPhone 開啟 Codex 工作並要求恢復服務，是人工恢復入口；Git 更新或 Cloudflare 都不能喚醒 Codex VM。

## 9. 常見問題

| 現象 | 處理 |
|---|---|
| Node version 引號錯誤 | 舊部署包 bug 已修正；使用 Git 內最新版，`node --version` 應為 v22+ |
| Git fetch 401/403 | 核對 origin、gh 登入及 repo 存取權；不要把 Token 寫進 remote URL |
| 本機改動或分岔 | 更新器會停止。先備份與人工檢視 `git status`，不要照不明指令 force reset |
| Cloudflare 404 | 核對真實 workers.dev URL，不要貼範例的 yourname |
| OAuth/登入過期 | 在應用程式目錄執行 `node node_modules/wrangler/bin/wrangler.js login`，只在這種失效時另行授權，然後重跑 Git 更新 |
| Cloudflare 401 | 可能用了不同 `.private`，或遠端 Secret 被新安裝覆寫；保留舊檔核對，不要隨便輪替 |
| 找不到 Durable Object | 用最新版完整部署腳本，單貼 worker.js 無法完成初次 SQLite migration |
| UI ERR_EMPTY_RESPONSE | 保留 console 錯誤；最新版明確用 UTF-8。舊版可用 `py -3 -X utf8 dashboard.py` 診斷 |
| 無近期快照 | VM 或 Agent 可能停止。先恢復 VM、核對模型與 Agent，勿反覆送單 |
| 429 Queue full | 等現有任務結束；不自動重送或繞過額度 |
| 模型 RSS 超限/圖片超 2MiB | 降低尺寸；目前沒有 GPU、壓縮自動重試或無限記憶體 |
| 歷史預覽不可用 | 雲端已過期且本機未快取時無法找回；不是 Git 更新能恢復的資料 |

遇到錯誤只提供錯誤文字與不含憑證的畫面，勿傳 `.private` 或 OAuth 設定。
